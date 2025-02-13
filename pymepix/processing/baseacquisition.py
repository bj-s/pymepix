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

"""Module deals with managing processing objects to form a data pipeline"""

from multiprocessing import Queue

import zmq

import pymepix.config.load_config as cfg
from pymepix.core.log import Logger
from pymepix.processing.usbtrainid import USBTrainID


class AcquisitionStage(Logger):
    """Defines a single acquisition stage

    Usually not created directly. Instead created by :class:`AcquisitionPipeline`
    Represent a single pipeline stage and handles management of queues and message passing
    as well as creation and destruction of processing objects.

    Processes are not created until build() is called and do not run until start() is called

    Parameters
    ------------
    stage: int
        Initial position in the pipeline, lower stages are executed first

    """

    def __init__(self, stage, num_processes=1):
        Logger.__init__(self, "AcqStage-{}".format(stage))
        self._stage_number = stage

        self._pipeline_objects = []
        self._pipeline_klass = None
        self._num_processes = num_processes
        self._running = False
        self._input_queue = None
        self._output_queue = None

        self._args = []
        self._kwargs = {}

    @property
    def stage(self):
        """Current position in the pipeline"""
        return self._stage_number

    @stage.setter
    def stage(self, value):
        self._stage_number = value

    @property
    def numProcess(self):
        """Number of processes to spawn when built

        Parameters
        ----------
        value: int
            Number of processes to spawn when acquisition starts

        Returns
        ----------
        int:
            Number of processes

        """

        return self._num_processes

    @numProcess.setter
    def numProcess(self, value):
        self._num_processes = max(1, value)

    def configureStage(self, pipeline_klass, *args, **kwargs):
        """Configures the stage with a particular processing class

        Parameters
        -----------
        pipeline_klass: :class:`BasePipeline`
            A pipeline class object

        *args:
            positional arguments to pass into the class init

        **kwargs:
            keyward arguments to pass into the class init


        """

        self.debug("Assigning stage {} to klass {}".format(self.stage, pipeline_klass))
        self._pipeline_klass = pipeline_klass

        # zmq socket for communication with write2disk thread
        # only initialize this in udpsampler
        from pymepix.processing.udpsampler import UdpSampler

        if pipeline_klass == UdpSampler:
            self.ctx = zmq.Context.instance()
            # self.udp_sock = self.ctx.socket(zmq.PAIR)
            # self.udp_sock.bind('tcp://127.0.0.1:40000')
            # self.info("zmq bind on 'tcp://127.0.0.1:40000'")

        self.setArgs(*args, **kwargs)

    def setArgs(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs

    @property
    def processes(self):
        return self._pipeline_objects

    def build(self, input_queue=None, output_queue=None, file_writer=None):
        self._input_queue = input_queue
        self._output_queue = output_queue

        self.debug(
            "Building stage with arguments {} {}".format(self._args, self._kwargs)
        )

        if self._output_queue is None:
            self.debug("I am creating the queue")
            self._output_queue = Queue()
        else:
            self.debug("Recieved the queue {}".format(output_queue))
        self.debug("Building stage {} ".format(self._stage_number))
        self.info("Creating {} processes".format(self._num_processes))
        for n in range(self._num_processes):

            p = self._pipeline_klass(
                *self._args,
                **self._kwargs,
                input_queue=self._input_queue,
                shared_output=self._output_queue,
            )
            p.daemon = True
            self._pipeline_objects.append(p)
            if self._output_queue is None:
                self._output_queue = p.outputQueues()[-1]

    @property
    def outputQueue(self):
        return self._output_queue

    def start(self):
        for p in self._pipeline_objects:
            zmq_port = cfg.default_cfg['zmq_port']
            if p.name.find("UdpSampler-") > -1:
                self.udp_sock = self.ctx.socket(zmq.PAIR)
                self.udp_sock.bind(f"tcp://127.0.0.1:{zmq_port}")
                self.info(f'zmq bind on "tcp://127.0.0.1:{zmq_port}"')

                if cfg.default_cfg["trainID"]["connected"]:
                    self.train_sock = self.ctx.socket(zmq.PAIR)
                    self.train_sock.bind(f"ipc:///tmp/train_sock{zmq_port}")
                    self.info(f'trainID bind on "ipc:///tmp/train_sock{zmq_port}"')
                    self.startTrainID()
            p.start()

    def stop(self, force=False):
        self.info("Stopping stage {}".format(self.stage))
        if self._input_queue is not None:
            # Put a none in and join all threads
            self._input_queue.put(None)
            for idx, p in enumerate(self._pipeline_objects):
                p.enable = False
                self.info("Waiting for process {}".format(idx))
                p.join(1.0)
                p.terminate()
                p.join()
                self.info("Process stop complete")
            if self._input_queue.get() is not None:
                self.error("Queue should only contain None!!")
                raise Exception("Queue contains more data")
            self._input_queue.close()
        else:
            for p in self._pipeline_objects:
                if p.name.find("UdpSampler-") > -1:
                    self.debug(f"closing zmq socket for tcp://127.0.0.1:{cfg.default_cfg['zmq_port']}")
                    self.udp_sock.close()
                    if cfg.default_cfg["trainID"]["connected"]:
                        self.stopTrainID()
                        self.debug(f"closing zmq socket for icp:///tmp/train_sock{cfg.default_cfg['zmq_port']}")
                        self.train_sock.close()
                p.enable = False
                self.info("Joining thread {}".format(p))
                p.join(1.0)
                p.terminate()
                p.join()
                self.info("Join complete")
        self.info("Stop complete")
        self._pipeline_objects = []

    def startTrainID(self):
        self.info(f"start USBTrainID process")
        # generate worker to save the data directly to disk
        self._trainIDRec = USBTrainID()
        self._trainIDRec.start()

    def stopTrainID(self):
        self.info(f"stopping USBTrainID process")
        self.train_sock.send_string("STOP RECORDING")
        self.train_sock.send_string("SHUTDOWN")
        self._trainIDRec.join(2.0)  # file still needs to be saved
        self._trainIDRec.terminate()
        self._trainIDRec.join()


class AcquisitionPipeline(Logger):
    """Class that manages various stages"""

    def __init__(self, name, data_queue):
        Logger.__init__(self, name + " AcqPipeline")
        self.info("Initializing pipeline")
        self._stages = []

        self._data_queue = data_queue

        self._running = False

    def addStage(self, stage_number, pipeline_klass, *args, num_processes=1, **kwargs):
        """Adds a stage to the pipeline"""
        stage = AcquisitionStage(stage_number, num_processes)
        self.info("Adding stage {} with klass {}".format(stage_number, pipeline_klass))
        stage.configureStage(pipeline_klass, *args, **kwargs)
        self._stages.append(stage)
        self._stages = sorted(self._stages, key=lambda x: x.stage)

    def getStage(self, stage_number):
        for x in self._stages:
            if x.stage == stage_number:
                return x

        return None

    @property
    def stages(self):
        return self._stages

    def start(self):
        """Starts all stages"""
        # Sort them by stage number

        self.info("Starting acquisition")
        # Build them
        previous_stage = None
        last_index = len(self._stages) - 1
        self.debug("Last index is {}".format(last_index))
        for idx, s in enumerate(self._stages):
            self.debug("Building stage {} {}".format(idx, s.stage))
            if previous_stage is not None:
                queues = previous_stage.outputQueue
                self.debug("Queues: {}".format(queues))
                if idx != last_index:
                    s.build(input_queue=queues)
                else:
                    self.debug("This is the last queue so output is the last one")
                    s.build(input_queue=queues, output_queue=self._data_queue)
            else:
                if idx != last_index:
                    s.build()
                else:
                    self.info("First stage shares output")
                    s.build(output_queue=self._data_queue)
            previous_stage = s
            self.debug("Last stage is {}".format(s))

        for s in self._stages:
            s.enable = True
            s.start()
        self._running = True

    @property
    def isRunning(self):
        return self._running

    def stop(self):
        """Stops all stages"""
        self.info("Stopping acquisition")
        self.debug(self._stages)
        if self._running is True:
            for s in self._stages:
                s.stop()
        self._running = False


def main():
    import logging
    import threading
    import time
    from multiprocessing.sharedctypes import Value

    from pymepix.processing.pipeline_packet_processor import PipelinePacketProcessor
    from pymepix.processing.udpsampler import UdpSampler

    # Create the logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    end_queue = Queue()

    acqpipline = AcquisitionPipeline("Test", end_queue)

    longtime = Value("I", 0)

    acqpipline.addStage(0, UdpSampler, ("127.0.0.1", 50000), longtime)
    acqpipline.addStage(2, PipelinePacketProcessor, num_processes=4)

    def get_queue_thread(queue):
        while True:
            value = queue.get()
            # messType, data = value
            # recieved.append(value[1])
            # print(value)
            if value is None:
                break

    t = threading.Thread(target=get_queue_thread, args=(end_queue,))
    t.daemon = True
    t.start()

    acqpipline.start()
    time.sleep(120.0)
    acqpipline.stop()
    end_queue.put(None)

    t.join()
    print("Done")


if __name__ == "__main__":
    main()
