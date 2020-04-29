#!/usr/bin/env python3

# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This script is the swarming task harness. This is the entry point for the
# Swarming bot.

import argparse
import glob
import json
import os
import subprocess
import sys
import time

def adb_press_key(keycode):
    cmd = ['adb', 'shell', 'input', 'keyevent', str(keycode)]
    p = subprocess.run(cmd, timeout=2, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('timeout', type=int, help='Timeout (duration limit for this test), in seconds')
    parser.add_argument('test_dir', help='Path to test directory, e.g. tests/foobar')
    parser.add_argument('out_dir', help='Path to output directory')
    args = parser.parse_args()

    #### Early checks and sanitization
    assert os.path.isdir(args.test_dir)
    test_dir = os.path.abspath(args.test_dir)
    assert os.path.isdir(args.out_dir)
    out_dir = os.path.abspath(args.out_dir)
    # bot-scripts/ contains test scripts
    assert os.path.isdir('bot-scripts')
    # agi/ contains the AGI build
    assert os.path.isdir('agi')
    agi_dir = os.path.abspath('agi')

    #### Check test parameters
    test_params = {}
    params_file = os.path.join(test_dir, 'params.json')
    assert os.path.isfile(params_file)
    with open(params_file, 'r') as f:
        test_params = json.load(f)
    assert 'script' in test_params.keys()
    test_script = os.path.abspath(os.path.join('bot-scripts', test_params['script']))
    assert os.path.isfile(test_script)

    #### Check Android device access
    cmd = ['adb', 'shell', 'true']
    p = subprocess.run(cmd, timeout=10)
    if p.returncode != 0:
        print('Error: zero or more than one device connected')
        return 1
    # Print device fingerprint
    cmd = ['adb', 'shell', 'getprop', 'ro.build.fingerprint']
    p = subprocess.run(cmd, timeout=10, capture_output=True, check=True, text=True)
    print('Device fingerprint: ' + p.stdout)

    #### Timeout: make room for pre-script checks and post-script cleanup.
    # All durations are in seconds.
    cleanup_timeout = 15
    if args.timeout < cleanup_timeout:
        print('Error: timeout must be higher than the time for cleanup duration ({} sec)'.format(cleanup_timeout))
        return 1
    test_timeout = args.timeout - cleanup_timeout

    #### Clean up logcat
    cmd = ['adb', 'logcat', '-c']
    p = subprocess.run(cmd, timeout=10, check=True)

    #### Launch test script
    print('Start test script "{}" with timeout of {} seconds'.format(test_script, test_timeout))
    cmd = [test_script, agi_dir, out_dir]
    test_returncode = None
    stdout_filename = os.path.abspath(os.path.join(out_dir, 'stdout.txt'))
    stderr_filename = os.path.abspath(os.path.join(out_dir, 'stderr.txt'))
    with open(stdout_filename, 'w') as stdout_file:
        with open(stderr_filename, 'w') as stderr_file:
            try:
                p = subprocess.run(cmd, timeout=test_timeout, cwd=test_dir, stdout=stdout_file, stderr=stderr_file)
                test_returncode = p.returncode
            except subprocess.TimeoutExpired as err:
                # Mirror returncode from unix 'timeout' command
                test_returncode = 124

    #### Dump the logcat
    logcat_file = os.path.join(out_dir, 'logcat.txt')
    with open(logcat_file, 'w') as f:
        cmd = ['adb', 'logcat', '-d']
        p = subprocess.run(cmd, timeout=5, check=True, stdout=f)

    #### Dump test outputs
    with open(stdout_filename, 'r') as f:
        print('#### Test stdout:')
        print(f.read())
    with open(stderr_filename, 'r') as f:
        print('#### Test stderr:')
        print(f.read())
    print('#### Test returncode:')
    print(test_returncode)

    #### Turn off the device screen
    # Key "power" (26) toggle between screen off and on, so first make sure to
    # have the screen on with key "wake up" (224), then press "power" (26)
    adb_press_key(224)
    # Wait a bit to let any kind of device wake up animation terminate
    time.sleep(2)
    adb_press_key(26)

    #### Test may fail halfway through, salvage any gfxtrace
    gfxtraces = glob.glob(os.path.join(test_dir, '*.gfxtrace'))
    if len(gfxtraces) != 0:
        salvage_dir = os.path.join(out_dir, 'harness-salvage')
        os.makedirs(salvage_dir, exist_ok=True)
        for gfx in gfxtraces:
            dest = os.path.join(salvage_dir, os.path.basename(gfx))
            os.rename(gfx, dest)

    #### Analyze the return code
    print('#### Test status:')
    if test_returncode == 124:
        print('TIMEOUT')
        print('Sleep a bit more to trigger a Swarming-level timeout, to disambiguate a timeout from a crash')
        time.sleep(cleanup_timeout)
    elif test_returncode != 0:
        print('FAIL')
    else:
        print('PASS')
    return test_returncode


if __name__ == '__main__':
    sys.exit(main())