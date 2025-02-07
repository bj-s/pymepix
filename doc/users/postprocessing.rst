===========================
Pymepix postprocessing
===========================

The raw data acquired from the camera could be processed from command line with the command.
The processing can also be triggered from the `PymepixViewer`.

Doing::

    pymepix post-process -f FILE -o OUTPUT_FILE [-t TIMEWALK_FILE] [-c CENT_TIMEWALK_FILE] [-n NUMBER_OF_PROCESSES]
    
The generated output file has HDF data format may contain the following datagroups in its root:

- **centroided**
- **raw**
- **timing/timepix**
- **triggers**

The **centroided** datagroups contains the data after centroiding processing. It consists of several datasets : "trigger nr", "x", "y", "tof", "tot avg", "tot max", "clustersize".
Where "trigger nr" is event number, "x"/"y" - coordinates of centroid, tof is time-of-flight (time-of-arrival corrected to the timewalk effect), "tot avg" average value of tot for all voxels in the cluster, "tot max" - max tot value, "clustersize" - the number of voxels in the detected cluster.

The **raw** datagroups contains event data - voxel data with tof synchronized to first triigger.
it consists of following datasets: "trigger nr", "x", "y", "tof", "tot".

The **timing/timepix** datagroup has only two datasets: "trigger nr", "timestamp". Where "trigger nr" contains triggering event numbers from first trigger, while dataset "time" contains the timestamps for the corresponding trigger event in nanosecond in absolute time from the timer of the camera.

Datagroup **triggers** may contain two subgroups "trigger1" and "trigger2" corresponding to the first and second trigger of the camera.
Each subgroup consists of only one dataset "time". These are firing times of the corresponding trigger starting from acquisition in seconds.
In case of first trigger these are the times of rising front of the detected trigger pulse. For the second trigger both rising and falling pulse edges are detected. Negative values corresponf to the falling edge.

Here's an example to retrieve the data from the HDF5 file into a Pandas DataFrame:

.. code:: python
    :numberlines: 1
    
    def get_tpx_data(fname: pathlib.PosixPath) -> pd.DataFrame:
        '''
        Get Timepix data from HDF5 file
        '''
        try:
            with h5py.File(fname, "r") as f:
                rawNr = f["raw/trigger nr"][:]
                rawTof = f["raw/tof"][:] * 1e6
                rawTot = f["raw/tot"][:]
                rawX = f["raw/x"][:]
                rawY = f["raw/y"][:]
                centNr = f["centroided/trigger nr"][:]
                centTof = f["centroided/tof"][:] * 1e6
                centTot = f["centroided/tot max"][:]
                centY = f["centroided/y"][:]
                centX = f["centroided/x"][:]
                size = f['centroided/clustersize'][:]

            raw_data = pd.DataFrame(
                np.column_stack((rawNr, rawTof, rawTot, rawX, rawY)),
                columns=("nr", "tof", "tot", "x", "y"),
            )
            cent_data = pd.DataFrame(
                np.column_stack((centNr, centTof, centTot, centX, centY, size)),
                columns=("nr", "tof", "tot", "x", "y", 'size'),
            )
            return raw_data, cent_data
        except:
            print(f'key not known or file "{fname}" not existing')



