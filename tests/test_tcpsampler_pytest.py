# This file is part of Pymepix
#
# In all scientific work using Pymepix, please reference it as
#
# A. F. Al-Refaie, M. Johny, J. Correa, D. Pennicard, P. Svihra, A. Nomerotski, S. Trippel, and J. Küpper:
# "PymePix: a python library for SPIDR readout of Timepix3", J. Inst. 14, P10003 (2019)
# https://doi.org/10.1088/1748-0221/14/10/P10003
# https://arxiv.org/abs/1905.07999
#
# Pymepix is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <https://www.gnu.org/licenses/>.

"""
module to test tcpsampler functionality
run: pytest test_tcpsampler_pytest.py
"""
import os
import socket
import time
from multiprocessing import Queue

import numpy as np

from pymepix.processing.acquisition import AcquisitionPipeline
from pymepix.util.tcpsampler import TcpSampler

address = ("127.0.0.1", 50000)


def send_data_TCP(packets, chunk_size, start=0, sleep=0.0001):
    ############
    # send data
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 50000))
    test_data = np.arange(
        start, start + packets * chunk_size, dtype=np.uint64
    )  # chunk size 135 -> max number=1_012_500
    test_data_view = memoryview(test_data)
    time.sleep(1)  # seems to be necessary if this function get called as a Process
    # first packet 0...134, second packet 135...269 and so on
    start = time.time()
    for i in range(0, len(test_data_view), chunk_size):
        sock.send(test_data_view[i : i + chunk_size])
        # time.sleep(sleep)  # if there's no sleep, packets get lost
    stop = time.time()
    dt = stop - start
    print(
        f"packets sent: {packets}, "
        f"bytes: {len(test_data_view.tobytes())}, "
        f"MBytes: {len(test_data_view.tobytes())*1e-6:.1f}, "
        f"{len(test_data_view.tobytes()) * 1e-6 / dt:.2f} MByte/s"
    )
    return test_data


def test_zmq_multifile():
    """
    test functionality of 1st acquisition pipeline step with data been put into Queue for pixelprocesor and thread to Raw2Disk
    """
    # Create the logger
    import logging
    import queue
    import threading
    import time
    from multiprocessing import Process
    from multiprocessing.sharedctypes import Value

    import zmq

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    end_queue = Queue()  # queue for PacketProcessor

    acqpipline = AcquisitionPipeline("Test", end_queue)

    test_value = Value("L", 0)

    acqpipline.addStage(0, TcpSampler, address, test_value)
    # acqpipline.addStage(2, PacketProcessor, num_processes=4)

    ###############
    # take data form Queue where PacketProcessor would be sitting
    ctx = zmq.Context.instance()

    def get_queue_thread(q):
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.PAIR)
        sock.connect("inproc://queueThread")
        sock.recv_string()  # receive establishing message

        received = []
        while True:
            try:
                value = q.get(
                    block=False, timeout=0.5
                )  # value = (Message.Type, [array, longtime])
                if value is None:
                    break
                messType, data = value
                received.append(data[0])
            except queue.Empty:
                pass
            # print(value)
        sock.send_pyobj(received)
        time.sleep(5)  # give zmq thread time to send data

    ##########
    # start acquisition pipeline
    acqpipline.start()

    ############
    # start 1st file
    """
    print('######### 1st file ##############')
    z_sock = ctx.socket(zmq.PAIR)
    z_sock.bind('inproc://queueThread')
    t = threading.Thread(target=get_queue_thread, args=(end_queue,))
    t.start()
    z_sock.send_string('hallo')  # establish connection, seems to be necessary to first send something from binding code....

    fname = f'./test-{time.strftime("%Y%m%d-%H%M%S")}.raw'
    #acqpipline._stages[0]._pipeline_objects[0].outfile_name = fname
    acqpipline._stages[0]._pipeline_objects[0].record = 1
    acqpipline._stages[0].udp_sock.send_string(fname)
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'OPENED':
        print(f'file {fname} opened')
    else:
        print(f'did not open {res}')
    time.sleep(1)  # give pipeline time to get started

    test_data = send_data(packets=10, chunk_size=10, sleep=0.0001)

    ###
    # finish acquisition 1st file
    time.sleep(5)  # permit thread time to empty queue
    acqpipline._stages[0]._pipeline_objects[0].record = 0
    acqpipline._stages[0]._pipeline_objects[0].close_file = 1
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'CLOSED':
        print(f'file {fname} closed')
    else:
        print(f'problem, {res}')
    time.sleep(1)
    end_queue.put(None)
    received = z_sock.recv_pyobj()

    # do the testing
    if len(received) > 1:
        data = np.concatenate(received)
    elif len(received) == 1:
        data = np.asarray(received[0])
    else:
        print('No packets received!!!')
        data = np.asarray([])

    print('data we got:')
    print(#np.frombuffer(data, dtype=np.uint64),
          #test_data,
          np.unique(np.frombuffer(data, dtype=np.uint64)).shape,
          np.frombuffer(data, dtype=np.uint64).shape,
          test_data.shape)
    # check for Queue content
    '''
    assert np.frombuffer(data, dtype=np.uint64).all() == test_data.all()
    assert np.frombuffer(data, dtype=np.uint64).sum() == test_data.sum()
    assert np.frombuffer(data, dtype=np.uint64).shape == test_data.shape
    '''
    # check for data in file
    assert np.fromfile(fname, dtype=np.uint64).all() == test_data.all()

    os.remove(fname)
    t.join()
    z_sock.close()

    if end_queue.empty():
        print('queue ist leer')

    ############
    # start 2nd file
    ############
    # start thread
    print('\n######### 2nd file ##############')
    z_sock = ctx.socket(zmq.PAIR)
    z_sock.bind('inproc://queueThread')
    t = threading.Thread(target=get_queue_thread, args=(end_queue,))
    t.start()
    z_sock.send_string('hallo')

    fname = f'./test-{time.strftime("%Y%m%d-%H%M%S")}.raw'
    # acqpipline._stages[0]._pipeline_objects[0].outfile_name = fname
    acqpipline._stages[0]._pipeline_objects[0].record = 1
    acqpipline._stages[0].udp_sock.send_string(fname)
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'OPENED':
        print(f'file {fname} opened')
    else:
        print(f'did not open {res}')

    test_data = send_data(packets=100, chunk_size=12, start=233, sleep=0.0001)

    # finish acquisition 2nd file
    time.sleep(5)  # permit thread time to empty queue
    acqpipline._stages[0]._pipeline_objects[0].record = 0
    acqpipline._stages[0]._pipeline_objects[0].close_file = 1
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'CLOSED':
        print(f'file {fname} closed')
    else:
        print(f'problem, {res}')
    end_queue.put(None)
    received = z_sock.recv_pyobj()

    # do the testing
    if len(received) > 1:
        data = np.concatenate(received)
    elif len(received) == 1:
        data = np.asarray(received[0])
    else:
        print('No packets received!!!')
        data = np.asarray([])

    print('data we got:')
    print(#np.frombuffer(data, dtype=np.uint64),
          #test_data,
          np.frombuffer(data, dtype=np.uint64).shape,
          np.unique(np.frombuffer(data, dtype=np.uint64)).shape,
          test_data.shape)
    # check for Queue content
    '''
    assert np.frombuffer(data, dtype=np.uint64).all() == test_data.all()
    assert np.frombuffer(data, dtype=np.uint64).sum() == test_data.sum()
    assert np.frombuffer(data, dtype=np.uint64).shape == test_data.shape
    # check for data in file
    assert np.fromfile(fname, dtype=np.uint64).all() == test_data.all()
    '''
    print('waiting for queue thread')
    t.join()
    z_sock.close()
    os.remove(fname)

    ############
    # start 3rd file
    ############
    # start thread
    print('\n######### 3rd file ##############')
    z_sock = ctx.socket(zmq.PAIR)
    z_sock.bind('inproc://queueThread')
    t = threading.Thread(target=get_queue_thread, args=(end_queue,))
    t.start()
    z_sock.send_string('hallo')

    fname = f'./test-{time.strftime("%Y%m%d-%H%M%S")}.raw'
    # acqpipline._stages[0]._pipeline_objects[0].outfile_name = fname
    acqpipline._stages[0]._pipeline_objects[0].record = 1
    acqpipline._stages[0].udp_sock.send_string(fname)
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'OPENED':
        print(f'file {fname} opened')
    else:
        print(f'did not open {res}')

    test_data = send_data(packets=300, chunk_size=135, start=4003, sleep=0.0001)

    # finish acquisition 3rd file
    time.sleep(5)  # permit thread time to empty queue
    acqpipline._stages[0]._pipeline_objects[0].record = 0
    acqpipline._stages[0]._pipeline_objects[0].close_file = 1
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'CLOSED':
        print(f'file {fname} closed')
    else:
        print(f'problem, {res}')
    end_queue.put(None)
    received = z_sock.recv_pyobj()

    # do the testing
    if len(received) > 1:
        data = np.concatenate(received)
    elif len(received) == 1:
        data = np.asarray(received[0])
    else:
        print('No packets received!!!')
        data = np.asarray([])

    print('data we got:')
    print(#np.frombuffer(data, dtype=np.uint64),
          #test_data,
          np.frombuffer(data, dtype=np.uint64).shape,
          np.unique(np.frombuffer(data, dtype=np.uint64)).shape,
          test_data.shape)
    # check for Queue content
    '''
    assert np.frombuffer(data, dtype=np.uint64).all() == test_data.all()
    assert np.frombuffer(data, dtype=np.uint64).sum() == test_data.sum()
    assert np.frombuffer(data, dtype=np.uint64).shape == test_data.shape
    '''
    # check for data in file
    assert np.fromfile(fname, dtype=np.uint64).all() == test_data.all()

    print('waiting for queue thread')
    t.join()
    z_sock.close()
    os.remove(fname)

    ############
    # start 4th file
    ############
    # start thread
    print('\n######### 4th file ##############')
    z_sock = ctx.socket(zmq.PAIR)
    z_sock.bind('inproc://queueThread')
    t = threading.Thread(target=get_queue_thread, args=(end_queue,))
    t.start()
    z_sock.send_string('hallo')

    fname = f'./test-{time.strftime("%Y%m%d-%H%M%S")}.raw'
    # acqpipline._stages[0]._pipeline_objects[0].outfile_name = fname
    acqpipline._stages[0]._pipeline_objects[0].record = 1
    acqpipline._stages[0].udp_sock.send_string(fname)
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'OPENED':
        print(f'file {fname} opened')
    else:
        print(f'did not open {res}')

    test_data = send_data(packets=100_000, chunk_size=135, start=15000, sleep=0)

    # finish acquisition 4th file
    time.sleep(5)  # permit thread time to empty queue
    acqpipline._stages[0]._pipeline_objects[0].record = 0
    acqpipline._stages[0]._pipeline_objects[0].close_file = 1
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == 'CLOSED':
        print(f'file {fname} closed')
    else:
        print(f'problem, {res}')
    end_queue.put(None)
    received = z_sock.recv_pyobj()

    # do the testing
    if len(received) > 1:
        data = np.concatenate(received)
    elif len(received) == 1:
        data = np.asarray(received[0])
    else:
        print('No packets received!!!')
        data = np.asarray([])

    print('data we got:')
    print(#np.frombuffer(data, dtype=np.uint64),
          #test_data,
          np.frombuffer(data, dtype=np.uint64).shape,
          np.unique(np.frombuffer(data, dtype=np.uint64)).shape,
          test_data.shape)
    # check for Queue content
    '''
    assert np.frombuffer(data, dtype=np.uint64).all() == test_data.all()
    assert np.frombuffer(data, dtype=np.uint64).sum() == test_data.sum()
    assert np.frombuffer(data, dtype=np.uint64).shape == test_data.shape
    '''
    # check for data in file
    assert np.fromfile(fname, dtype=np.uint64).all() == test_data.all()
    assert np.fromfile(fname, dtype=np.uint64).sum() == test_data.sum()
    assert np.fromfile(fname, dtype=np.uint64).shape == test_data.shape

    print('waiting for queue thread')
    t.join()
    z_sock.close()
    os.remove(fname)
    """

    ############
    # send data as fast as possible
    ############
    # start thread
    print("\n######### 5th file ##############")
    z_sock = ctx.socket(zmq.PAIR)
    z_sock.bind("inproc://queueThread")
    t = threading.Thread(target=get_queue_thread, args=(end_queue,))
    t.start()
    z_sock.send_string("hallo")

    fname = f'./test-{time.strftime("%Y%m%d-%H%M%S")}.raw'
    # acqpipline._stages[0]._pipeline_objects[0].outfile_name = fname
    acqpipline._stages[0]._pipeline_objects[0].record = 1
    acqpipline._stages[0].udp_sock.send_string(fname)  # open file
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == "OPENED":
        print(f"file {fname} opened")
    else:
        print(f"did not open {res}")

    ############
    # send data
    packets = 60_000
    chunk_size = 138
    test_data = np.arange(0, packets * chunk_size, dtype=np.uint64)
    # test_data = send_data(packets=10_000, chunk_size=135, start=15000, sleep=1e-4)
    p = Process(target=send_data_TCP, args=(packets, chunk_size, 0, 0))
    p.start()
    p.join()

    # finish acquisition 5th file
    time.sleep(5)  # permit thread time to empty queue
    acqpipline._stages[0]._pipeline_objects[0].record = 0
    acqpipline._stages[0]._pipeline_objects[0].close_file = 1
    acqpipline._stages[0]._pipeline_objects[0].enable = 0
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == "CLOSED":
        print(f"file {fname} closed")
    else:
        print(f"problem, {res}")
    end_queue.put(None)
    received = z_sock.recv_pyobj()

    # do the testing
    if len(received) > 1:
        data = np.concatenate(received)
    elif len(received) == 1:
        data = np.asarray(received[0])
    else:
        print("No packets received!!!")
        data = np.asarray([])

    print("data we got:")
    print(  # np.frombuffer(data, dtype=np.uint64),
        # test_data,
        np.frombuffer(data, dtype=np.uint64).shape,
        np.unique(np.frombuffer(data, dtype=np.uint64)).shape,
        test_data.shape,
    )
    # check for Queue content
    """
    assert np.frombuffer(data, dtype=np.uint64).all() == test_data.all()
    assert np.frombuffer(data, dtype=np.uint64).sum() == test_data.sum()
    assert np.frombuffer(data, dtype=np.uint64).shape == test_data.shape
    """
    # check for data in file
    print(
        np.fromfile(fname, dtype=np.uint64).shape,
        test_data.shape,
        np.fromfile(fname, dtype=np.uint64).shape[0] / test_data.shape[0],
    )
    """
    assert np.fromfile(fname, dtype=np.uint64).all() == test_data.all()
    assert np.fromfile(fname, dtype=np.uint64).sum() == test_data.sum()
    assert np.fromfile(fname, dtype=np.uint64).shape == test_data.shape
    """

    if t.is_alive():
        end_queue.put(None)
        print("waiting for queue thread")
        t.join()
    print("close zmq")
    z_sock.close()
    print("closed zmq")
    # os.remove(fname)

    ############
    # shut everything down
    print("finish raw2disk")
    res = acqpipline._stages[0].udp_sock.send_string("SHUTDOWN")
    acqpipline.stop()

    print("Done and done")


def test_real_data_packetprocessor():
    """receive actual data from TPX"""
    # Create the logger
    import logging
    import time
    from multiprocessing.sharedctypes import Value

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    end_queue = Queue()  # queue for PacketProcessor
    test_value = Value("L", 0)
    acqpipline = AcquisitionPipeline("Test", end_queue)
    acqpipline.addStage(0, TcpSampler, address, test_value)
    # acqpipline.addStage(2, PacketProcessor, num_processes=4)

    ##########
    # start acquisition pipeline
    acqpipline.start()

    fname = f'./test-{time.strftime("%Y%m%d-%H%M%S")}.raw'
    start = time.time()
    acqpipline._stages[0]._pipeline_objects[0].record = True
    acqpipline._stages[0].udp_sock.send_string(fname)
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == "OPENED":
        print(f"file {fname} opened")
    else:
        print(f"did not open {res}")
    time.sleep(40)  # record for n seconds

    acqpipline._stages[0]._pipeline_objects[0].record = False
    stop = time.time()
    acqpipline._stages[0]._pipeline_objects[0].close_file = True
    res = acqpipline._stages[0].udp_sock.recv_string()
    if res == "CLOSED":
        print(f"file {fname} closed")
    else:
        print(f"problem, {res}")
        print("data we got from raw2disk:")
    dt = stop - start
    print(
        f"received MByte/s: {np.fromfile(fname, dtype=np.uint8).shape[0] / dt * 1e-6:.2f}"
    )

    # close everything
    os.remove(fname)
    acqpipline._stages[0]._pipeline_objects[0].enable = False
    res = acqpipline._stages[0].udp_sock.send_string("SHUTDOWN")
    acqpipline.stop()

    print("Done and done")


if __name__ == "__main__":
    # test_zmq_multifile()
    # test_zmq_singlefile()
    test_real_data_packetprocessor()
