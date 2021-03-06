#!/usr/bin/env python
#
# csmap - Conservation score mapper
#
# Author: Jian-Long Huang (jianlong@ntu.edu.tw)
# Version: 1.10
# Created: 2013.4.1
#
# Usage: csmap <input.fa> <scores.tar> <output.txt>

import re
import sys
import bisect
import tarfile
import mmap
import contextlib


class WigData:
    def __init__(self, object):
        self.file = object
        self.starts = []
        self.start_offset = {}
        self.max_offset = {}

    def set_offset(self, start, start_offset, max_offset):
        self.starts.append(start)
        self.start_offset.update({start: start_offset})
        self.max_offset.update({start: max_offset})

    def map(self, start, end, partial=False):
        assert start < end, 'Start must be lower than end.'

        i = bisect.bisect_right(self.starts, int(start))

        if i == 0:
            # Start is at first position
            if partial:
                # Begin to score partial sequences
                j = bisect.bisect_right(self.starts, int(end))
                if j == 0:
                    # End is at first position
                    return None
                elif j == 1:
                    # End is at second position
                    start_offset = self.start_offset[self.starts[0]]
                    offset = (end - self.starts[0] + 1) * 6 - 1
                    return self.get_scores(start_offset, offset)
                else:
                    # End spans more than one regions
                    scores = []
                    for k in range(j):
                        start_offset = self.start_offset[self.starts[k]]
                        offset = self.max_offset.get(self.starts[k])
                        scores = scores + self.get_scores(start_offset, offset)
                    start_offset = self.start_offset[self.starts[j]]
                    offset = (end - self.starts[j] + 1) * 6 - 1
                    return scores + self.get_scores(start_offset, offset)
            else:
                # No data
                return None
        elif (start - self.starts[i - 1]) * 6 + (end - start + 1) * 6 > self.max_offset.get(self.starts[i - 1]):
            # Stop is out of range
            if partial:
                # Begin to score parial sequences
                if (start - self.starts[i - 1]) * 6 < self.max_offset.get(self.starts[i - 1]):
                    # Start is in region
                    j = bisect.bisect_right(self.starts, int(end))
                    if j == i:
                        # End is at the same array order of start.
                        # tested
                        start_offset = self.start_offset[self.starts[i - 1]] + (start - self.starts[i - 1]) * 6
                        offset = self.max_offset.get(self.starts[i - 1]) - (start - self.starts[i - 1]) * 6 - 1
                        return self.get_scores(start_offset, offset)
                    else:
                        # End spans more than one regions
                        scores = []
                        start_offset = self.start_offset[self.starts[i - 1]] + (start - self.starts[i - 1]) * 6
                        offset = self.max_offset.get(self.starts[i - 1]) - (start - self.starts[i - 1]) * 6 - 1
                        scores = scores + self.get_scores(start_offset, offset)
                        if j - i == 1:
                            # End is at next position
                            # tested
                            if self.starts[i] + self.max_offset.get(self.starts[i]) / 6 < end:
                                start_offset = self.start_offset[self.starts[i]]
                                offset = self.max_offset.get(self.starts[i]) - 1
                                return scores + self.get_scores(start_offset, offset)
                            else:
                                start_offset = self.start_offset[self.starts[i]]
                                offset = (end - self.starts[i] + 1) * 6 - 1
                                return scores + self.get_scores(start_offset, offset)
                        else:
                            for k in range(i, j - 1):
                                start_offset = self.start_offset[self.starts[k]]
                                offset = self.max_offset.get(self.starts[k]) - 1
                                scores = scores + self.get_scores(start_offset, offset)
                            start_offset = self.start_offset[self.starts[j - 1]]
                            if (end - self.starts[j - 1] + 1) * 6 < self.max_offset.get(self.starts[j - 1]):
                                offset = (end - self.starts[j - 1] + 1) * 6 - 1
                            else:
                                offset = self.max_offset.get(self.starts[j - 1])
                            return scores + self.get_scores(start_offset, offset)
                else:
                    # Start is not in region
                    j = bisect.bisect_right(self.starts, int(end))
                    if j == i:
                        # End is not in region
                        return None
                    elif j - i == 1:
                        # End is at next position
                        if self.starts[i] + self.max_offset.get(self.starts[i]) / 6 < end:
                            start_offset = self.start_offset[self.starts[i]]
                            offset = self.max_offset.get(self.starts[i]) - 1
                            return self.get_scores(start_offset, offset)
                        else:
                            start_offset = self.start_offset[self.starts[i]]
                            offset = (end - self.starts[i] + 1) * 6 - 1
                            return self.get_scores(start_offset, offset)
                    else:
                        scores = []
                        for k in range(i, j - 1):
                            start_offset = self.start_offset[self.starts[k]]
                            offset = self.max_offset.get(self.starts[k]) - 1
                            scores = scores + self.get_scores(start_offset, offset)
                        start_offset = self.start_offset[self.starts[j - 1]]
                        if (end - self.starts[j - 1] + 1) * 6 < self.max_offset.get(self.starts[j - 1]):
                            offset = (end - self.starts[j - 1] + 1) * 6 - 1
                        else:
                            offset = self.max_offset.get(self.starts[j - 1]) - 1
                        return scores + self.get_scores(start_offset, offset)
            else:
                return None
        else:
            start_offset = self.start_offset[self.starts[i - 1]] + (start - self.starts[i - 1]) * 6
            offset = (end - start + 1) * 6 - 1
            return self.get_scores(start_offset, offset)

    def get_scores(self, start_offset, offset):
        self.file.seek(start_offset)
        return list(map(float, self.file.read(offset).split(b'\n')))


class WigLister:
    def __init__(self, filename):
        self.wig_data_list = {}
        self.chroms = []

        header = re.compile(b'# (.+)')

        if tarfile.is_tarfile(filename):
            tar_file = tarfile.open(filename, 'r')
        else:
            sys.exit('File ' + filename + ' is not a tar file.')

        for line in tar_file.extractfile('index'):
            if header.match(line):
                chrom = header.match(line).group(1).decode('utf-8')
                self.chroms.append(chrom)
                wig_data = WigData(tar_file.extractfile(chrom))
                self.wig_data_list.update({chrom: wig_data})
            else:
                data = line.rstrip().decode('utf-8').split(' ')
                self.wig_data_list.get(chrom).set_offset(*map(int, data))

    def get_chroms(self):
        return self.chroms

    def map(self, chrom, start, end, partial=False):
        assert start < end, 'Start must be lower than end.'

        return self.wig_data_list.get(chrom).map(start, end, partial)


def parse(fi, score_filepath, partial=False):
    """
    Input: file object
    This function is for web service.
    """

    score_data = WigLister(score_filepath)
    result = ['\t'.join(['seqname',
                         'chrname',
                         'start',
                         'end',
                         'score'])]
    file_lineno = 0

    for line in fi:
        line = line.rstrip()
        file_lineno += 1

        try:
            data = line.split()
            seq_name = data[0]
            chr_name = data[1]
            chr_start = int(data[2])
            chr_end = int(data[3])
        except ValueError:
            return None, file_lineno
        except IndexError:
            return None, file_lineno
        else:
            if chr_start >= chr_end:
                # Start must be lower than end
                return None, file_lineno

            if chr_name in score_data.get_chroms():
                scores = score_data.map(chr_name, chr_start, chr_end, partial)

                if scores is not None:
                    if partial is False:
                        assert len(scores) == chr_end - chr_start + 1, 'Fetching error!'

                    score_avg = round(sum(scores) / len(scores), 3)
                    result.append('\t'.join([seq_name,
                                             chr_name,
                                             str(chr_start),
                                             str(chr_end),
                                             str(score_avg)]))

                else:
                    result.append('\t'.join([seq_name,
                                             chr_name,
                                             str(chr_start),
                                             str(chr_end),
                                             'NA']))
            else:
                result.append('\t'.join([seq_name,
                                         chr_name,
                                         str(chr_start),
                                         str(chr_end),
                                         'NA']))

    return '\n'.join(result), file_lineno


def main(argvs):
    # Check arguments
    if len(argvs) != 3:
        sys.exit('Usage: csmap <input.fa> <scores.tar> <output.txt>')

    # Parse score files
    print('Unpacking score files...')
    score_data = WigLister(argvs[1])

    # Start to map
    print('OK!')
    print('Starting to map...')
    fa_header = re.compile('.*range=(.+):(\d+)-(\d+).*')

    with open(argvs[0], 'r+') as fi, open(argvs[2], 'w') as fo:
        with contextlib.closing(mmap.mmap(fi.fileno(), 0)) as m:
            fo.write('sequence_name\tavg_conservation_score\n')

            while True:
                offset = m.find('>')

                if offset == -1:
                    break

                m.seek(offset)
                header = fa_header.match(m.readline().lstrip())

                if header is None:
                    sys.exit('Format error in the fasta file, please check it.')

                seq_name = header.group(0).rstrip()[1:]
                chr_name = header.group(1)
                chr_start = int(header.group(2))
                chr_end = int(header.group(3))

                if chr_name not in score_data.get_chroms():
                    print('No chromosome is found in score files: ' + seq_name)
                    continue

                scores = score_data.map(chr_name, chr_start, chr_end)

                if scores is None:
                    print('No score data is found: ' + seq_name)
                    continue
                else:
                    # assert len(scores) == chr_end - chr_start + 1, 'Fetching error!'

                    score_avg = round(sum(scores) / len(scores), 3)
                    fo.write(seq_name + '\t' + str(score_avg) + '\n')
                    fo.flush()


if __name__ == '__main__':
    main(sys.argv[1:])
    print('Successfully executed!')
