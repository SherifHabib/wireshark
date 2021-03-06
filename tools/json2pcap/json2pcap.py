#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# Copyright 2017, Martin Kacer <kacer.martin[AT]gmail.com>
#
# Wireshark - Network traffic analyzer
# By Gerald Combs <gerald@wireshark.org>
# Copyright 1998 Gerald Combs
#
# SPDX-License-Identifier: GPL-2.0-or-later

import sys
import json
import operator
import copy
import os
import binascii
import array
import argparse
import subprocess
from collections import OrderedDict

def make_unique(key, dct):
    counter = 0
    unique_key = key

    while unique_key in dct:
        counter += 1
        unique_key = '{}_{}'.format(key, counter)
    return unique_key


def parse_object_pairs(pairs):
    dct = OrderedDict()
    for key, value in pairs:
        if key in dct:
            key = make_unique(key, dct)
        dct[key] = value

    return dct

#
# ********* PY TEMPLATES *********
#
def read_py_function(name):
    s = ''
    record = False
    indent = 0

    file = open(__file__)
    for line in file:

        ind = len(line) - len(line.lstrip())

        if (line.find("def " + name) != -1):
            record = True
            indent = ind
        elif (record == True and indent == ind and len(line) > 1):
            record = False

        if (record == True):
            s = s + line

    file.close()
    return s

py_header = """#!/usr/bin/env python
# -*- coding: utf-8 -*-

# File generated by json2pcap.py
# json2pcap.py created by Martin Kacer, 2017

import os
import binascii
import array
import sys
import subprocess
from collections import OrderedDict

# *****************************************************
# *     PACKET PAYLOAD GENERATED FROM INPUT PCAP      *
# *     Modify this function to edit the packet       *
# *****************************************************
def main():
    d = OrderedDict()
"""

py_footer = """    generate_pcap(d)

# *****************************************************
# *             FUNCTIONS from TEMPLATE               *
# *    Do not edit these functions if not required    *
# *****************************************************

"""
py_footer = py_footer + read_py_function("to_pcap_file")
py_footer = py_footer + read_py_function("hex_to_txt")
py_footer = py_footer + read_py_function("to_bytes")
py_footer = py_footer + read_py_function("lsb")
py_footer = py_footer + read_py_function("rewrite_frame")
py_footer = py_footer + read_py_function("assemble_frame")
py_footer = py_footer + read_py_function("generate_pcap")

py_footer = py_footer + """

if __name__ == '__main__':
    main()
"""
#
# ***** End of PY TEMPLATES ******
#



#
# ********** FUNCTIONS ***********
#
def to_pcap_file(filename, output_pcap_file):
    subprocess.call(["text2pcap", filename, output_pcap_file])

def hex_to_txt(hexstring, output_file):
    h = hexstring.lower()

    file = open(output_file, 'a')

    for i in range(0, len(h), 2):
        if(i % 32 == 0):
            file.write(format(i / 2, '06x') + ' ')

        file.write(h[i:i + 2] + ' ')

        if(i % 32 == 30):
            file.write('\n')

    file.write('\n')
    file.close()

def raw_flat_collector(dict):
    if hasattr(dict, 'items'):
        for k, v in dict.items():
            if k.endswith("_raw"):
                yield k, v
            else:
                for val in raw_flat_collector(v):
                    yield val


# d - input dictionary, parsed from json
# r - result dictionary
# frame_name - parent protocol name
# frame_position - parent protocol position
def py_generator(d, r, frame_name='frame_raw', frame_position=0):
    if (d is None or d is None):
        return

    if hasattr(d, 'items'):
        for k, v in d.items():

            # no recursion
            if ( k.endswith("_raw") or ("_raw_" in k) ):
                if (isinstance(v[1], (list, tuple)) or isinstance(v[2], (list, tuple)) ):
                    #i = 1;
                    for _v in v:
                        h = _v[0]
                        p = _v[1]
                        l = _v[2] * 2
                        b = _v[3]
                        t = _v[4]
                        if (len(h) != l):
                            l = len(h)

                        p = p - frame_position

                        # Add into result dictionary
                        key = str(k).replace('.', '_')
                        key = make_unique(key, r)

                        fn = frame_name.replace('.', '_')
                        if (fn == key):
                            fn = None
                        value = [fn , h, p, l, b, t]

                        r[key] = value

                else:
                    h = v[0]
                    p = v[1]
                    l = v[2] * 2
                    b = v[3]
                    t = v[4]
                    if (len(h) != l):
                        l = len(h)

                    p = p - frame_position

                    # Add into result dictionary
                    key = str(k).replace('.', '_')
                    key = make_unique(key, r)

                    fn = frame_name.replace('.', '_')
                    if (fn == key):
                        fn = None
                    value = [fn , h, p, l, b, t]

                    r[key] = value

            # recursion
            else:
                if isinstance(v, dict):
                    fn = frame_name
                    fp = frame_position

                    # if there is also preceding raw protocol frame use it
                    # remove tree suffix
                    key = k
                    if (key.endswith("_tree") or ("_tree_" in key)):
                        key = key.replace('_tree', '')

                    raw_key = key + "_raw"
                    if (raw_key in d):
                        # f =  d[raw_key][0]
                        fn = raw_key
                        fp = d[raw_key][1]


                    py_generator(v, r, fn, fp)

                elif isinstance(v, (list, tuple)):

                    fn = frame_name
                    fp = frame_position

                    # if there is also preceding raw protocol frame use it
                    # remove tree suffix
                    key = k
                    if (key.endswith("_tree") or ("_tree_" in key)):
                        key = key.replace('_tree', '')

                    raw_key = key + "_raw"
                    if (raw_key in d):
                        fn = raw_key
                        fp = d[raw_key][1]

                    for _v in v:
                        py_generator(_v, r, frame_name, frame_position)




# To emulate Python 3.2
def to_bytes(n, length, endianess='big'):
    h = '%x' % n
    s = ('0' * (len(h) % 2) + h).zfill(length * 2).decode('hex')
    return s if endianess == 'big' else s[::-1]

# Returns the index, counting from 0, of the least significant set bit in x
def lsb(x):
    return (x & -x).bit_length() - 1

# Rewrite frame
# h - hex bytes
# p - position
# l - length
# b - bitmask
# t - type
def rewrite_frame(frame_raw, h, p, l, b, t):
    # no bitmask
    if(b == 0):
        if (len(h) != l):
            l = len(h)
        return frame_raw[:p] + h + frame_raw[p + l:]
    # bitmask
    else:
        # get hex string from frame which will be replaced
        _h = frame_raw[p:p + l]

        # add 0 padding to have correct length
        if (len(_h) % 2 == 1):
            _h = '0' + _h
        if (len(h) % 2 == 1):
            h = '0' + h

        # Only replace bits defined by mask
        # new_hex = (old_hex & !mask) | (new_hex & mask)
        _H = _h.decode("hex")
        _H = array.array('B', _H)

        M = to_bytes(b, len(_H))
        M = array.array('B', M)
        # shift mask aligned to position
        for i in range(len(M)):
            if (i + p / 2) < len(M):
                M[i] = M[i + p / 2]
            else:
                M[i] = 0x00

        H = h.decode("hex")
        H = array.array('B', H)

        # for i in range(len(_H)):
        #    print "{0:08b}".format(_H[i]),
        # print
        # for i in range(len(M)):
        #    print "{0:08b}".format(M[i]),
        # print

        j = 0;
        for i in range(len(_H)):
            if (M[i] != 0):
                v = H[j] << lsb(M[i])
                # print "Debug: {0:08b}".format(v),
                _H[i] = (_H[i] & ~M[i]) | (v & M[i])
                # print "Debug: " + str(_H[i]),
                j = j + 1;

        # for i in range(len(_H)):
        #    print "{0:08b}".format(_H[i]),
        # print

        masked_h = binascii.hexlify(_H)

        return frame_raw[:p] + masked_h + frame_raw[p + l:]


def assemble_frame(d):
    input = d['frame_raw'][1]
    isFlat = False
    linux_cooked_header = False;
    while(isFlat == False):
        isFlat = True
        for key, val in d.items():
            h = str(val[1])     # hex
            p = val[2] * 2      # position
            l = val[3] * 2      # length
            b = val[4]          # bitmask
            t = val[5]          # type

            if (key == "sll_raw"):
                linux_cooked_header = True;

            # only if the node is not parent
            isParent = False
            for k, v in d.items():
                if (v[0] == key):
                    isParent = True
                    isFlat = False
                    break

            if (isParent == False and val[0] is not None):
                d[val[0]][1] = rewrite_frame(d[val[0]][1], h, p, l, b, t)
                del d[key]

    output = d['frame_raw'][1]

    # for Linux cooked header replace dest MAC and remove two bytes to reconstruct normal frame using text2pcap
    if (linux_cooked_header):
        output = "000000000000" + output[6*2:] # replce dest MAC
        output = output[:12*2] + "" + output[14*2:] # remove two bytes before Protocol

    return output

def generate_pcap(d):
    # 1. Assemble frame
    input = d['frame_raw'][1]
    output = assemble_frame(d)
    print(input)
    print(output)

    # 2. Testing: compare input and output for not modified json
    if (input != output):
        print("Modified frames: ")
        s1 = input
        s2 = output
        print(s1)
        print(s2)
        if (len(s1) == len(s2)):
            d = [i for i in xrange(len(s1)) if s1[i] != s2[i]]
            print(d)

    # 3. Open TMP file used by text2pcap
    file = sys.argv[0] + '.tmp'
    f = open(file,'w')
    hex_to_txt(output, file)
    f.close()

    # 4. Generate pcap
    to_pcap_file(sys.argv[0] + '.tmp', sys.argv[0] + '.pcap')
    print("Generated " + sys.argv[0] + ".tmp")
    print("Generated " + sys.argv[0] + ".pcap")

#
# ************ MAIN **************
#
parser = argparse.ArgumentParser(description="""
Utility to generate pcap from json format.

Packet modification:
In input json  it is possible to  modify the raw values  of decoded fields.
The  output  pcap  will  include  the modified  values.  The  algorithm  of
generating the output pcap is to get all raw hex fields from input json and
then  assembling them  by layering  from longest  (less decoded  fields) to
shortest  (more decoded  fields). It  means if  the modified  raw field  is
shorter field (more decoded field) it takes precedence against modification
in longer field  (less decoded field). If the json  includes duplicated raw
fields with  same position and  length, the behavior is  not deterministic.
For manual packet editing it is  always possible to remove any not required
raw fields from json, only frame_raw is field mandatory for reconstruction.

Packet modification with -p switch:
The python  script is generated  instead of  pcap. This python  script when
executed  will  generate the  pcap  of  1st  packet  from input  json.  The
generated code includes the decoded fields and the function to assembly the
packet.  This enables  to modify  the script  and programmatically  edit or
encode the packet variables. The assembling algorithm is different, because
the decoded packet fields are relative and points to parent node with their
position (compared to input json which has absolute positions).

""", formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('infile', nargs='+', help='json generated by tshark -T jsonraw or by tshark -T json -x')
parser.add_argument('-p', '--python', help='generate python payload instead of pcap (only 1st packet)', default=False, action='store_true')
args = parser.parse_args()

# read JSON
infile = args.infile[0]

with open(infile) as data_file:
    #json = json.load(data_file, object_pairs_hook=OrderedDict)
    json = json.load(data_file, object_pairs_hook=parse_object_pairs)

input_frame_raw = ''
frame_raw = ''

# Generate pcap
if args.python == False:
    # open TMP file used by text2pcap
    file = infile + '.tmp'
    f = open(file, 'w')

    # Iterate over packets in JSON
    for packet in json:
        _list = []
        linux_cooked_header = False;

        # get flat raw fields into _list
        for raw in raw_flat_collector(packet['_source']['layers']):
            if (raw[0] == "frame_raw"):
                frame_raw = raw[1][0]
                input_frame_raw = copy.copy(frame_raw)
            else:
                _list.append(raw[1])
            if (raw[0] == "sll_raw"):
                linux_cooked_header = True

        # sort _list
        sorted_list = sorted(_list, key=operator.itemgetter(1), reverse=False)
        sorted_list = sorted(sorted_list, key=operator.itemgetter(2), reverse=True)
        # print("Debug: " + str(sorted_list))

        # rewrite frame
        for raw in sorted_list:
            h = str(raw[0])  # hex
            p = raw[1] * 2  # position
            l = raw[2] * 2  # length
            b = raw[3]  # bitmask
            t = raw[4]  # type

            if (isinstance(p, (list, tuple)) or isinstance(l, (list, tuple))):
                for r in raw:
                    _h = str(r[0])  # hex
                    _p = r[1] * 2  # position
                    _l = r[2] * 2  # length
                    _b = r[3]  # bitmask
                    _t = r[4]  # type
                    # print("Debug: " + str(raw))
                    frame_raw = rewrite_frame(frame_raw, _h, _p, _l, _b, _t)

            else:
                # print("Debug: " + str(raw))
                frame_raw = rewrite_frame(frame_raw, h, p, l, b, t)

        # for Linux cooked header replace dest MAC and remove two bytes to reconstruct normal frame using text2pcap
        if (linux_cooked_header):
           frame_raw = "000000000000" + frame_raw[6 * 2:]  # replce dest MAC
           frame_raw = frame_raw[:12 * 2] + "" + frame_raw[14 * 2:]  # remove two bytes before Protocol

        # Testing: remove comment to compare input and output for not modified json
        if (input_frame_raw != frame_raw):
            print("Modified frames: ")
            s1 = input_frame_raw
            s2 = frame_raw
            print(s1)
            print(s2)
            if (len(s1) == len(s2)):
                d = [i for i in xrange(len(s1)) if s1[i] != s2[i]]
                print(d)

        hex_to_txt(frame_raw, file)

    f.close()
    to_pcap_file(infile + '.tmp', sys.argv[1] + '.pcap')
    os.remove(infile + '.tmp')

# Generate python payload only for first packet
else:
    file = infile + '.py'
    f = open(file, 'w')

    for packet in json:
        f.write(py_header)

        r = OrderedDict({})

        #print "packet = " + str(packet['_source']['layers'])
        py_generator(packet['_source']['layers'], r)

        for key, value in r.iteritems() :
            f.write("    d['" + key + "'] =",)
            f.write(" " + str(value) + "\n")

        f.write(py_footer)

        # Currently only first packet is used from pcap
        f.close

        print("Generated " + infile + '.py')

        break
