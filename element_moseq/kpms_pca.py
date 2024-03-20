from datetime import datetime, timezone
import inspect
import os
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import datajoint as dj
import importlib

from element_interface.utils import find_full_path
from .readers.kpms_reader import generate_kpms_dj_config, load_kpms_dj_config
from keypoint_moseq import (
    setup_project, 
    load_config, 
    load_keypoints
)


schema = dj.schema()
_linking_module = None


def activate(
    pca_schema_name: str,
    *,
    create_schema: bool = True,
    create_tables: bool = True,
    linking_module: str = None,
):
    """Activate this schema.

    Args:
        pca_schema_name (str): A string containing the name of the pca schema.
        create_schema (bool): If True (default), schema  will be created in the database.
        create_tables (bool): If True (default), tables related to the schema will be created in the database.
        linking_module (str): A string containing the module name or module containing the required dependencies to activate the schema.

    Dependencies:
    Functions:
        get_kpms_root_data_dir(): Returns absolute path for root data director(y/ies) with all behavioral recordings, as (list of) string(s)
        get_kpms_processed_data_dir(): Optional. Returns absolute path for processed data. Defaults to session video subfolder.
    """

    if isinstance(linking_module, str):
        linking_module = importlib.import_module(linking_module)
    assert inspect.ismodule(
        linking_module
    ), "The argument 'dependency' must be a module's name or a module"

    assert hasattr(
        linking_module, "get_kpms_root_data_dir"
    ), "The linking module must specify a lookup function for a root data directory"

    global _linking_module
    _linking_module = linking_module

    # activate
    schema.activate(
        pca_schema_name,
        create_schema=create_schema,
        create_tables=create_tables,
        add_objects=_linking_module.__dict__,
    )


# -------------- Functions required by the element-moseq ---------------


def get_kpms_root_data_dir() -> list:
    """Pulls relevant func from parent namespace to specify root data dir(s).

    It is recommended that all paths in DataJoint Elements stored as relative
    paths, with respect to some user-configured "root" director(y/ies). The
    root(s) may vary between data modalities and user machines. Returns a full path
    string or list of strings for possible root data directories.
    """
    root_directories = _linking_module.get_kpms_root_data_dir()
    if isinstance(root_directories, (str, Path)):
        root_directories = [root_directories]

    if (
        hasattr(_linking_module, "get_kpms_processed_data_dir")
        and get_kpms_processed_data_dir() not in root_directories
    ):
        root_directories.append(_linking_module.get_kpms_processed_data_dir())

    return root_directories


def get_kpms_processed_data_dir() -> Optional[str]:
    """Pulls relevant func from parent namespace. Defaults to KPMS's project /videos/.

    Method in parent namespace should provide a string to a directory where KPMS output
    files will be stored. If unspecified, output files will be stored in the
    session directory 'videos' folder, per DeepLabCut default.
    """
    if hasattr(_linking_module, "get_kpms_processed_data_dir"):
        return _linking_module.get_kpms_processed_data_dir()
    else:
        return None


# ----------------------------- Table declarations ----------------------


@schema
class PoseEstimationMethod(dj.Lookup):
    """Table to store the pose estimation methods supported by the keypoint loader of `keypoint-moseq` package.

    Attributes:
        format_method (str): Pose estimation method (e.g. deeplabcut, sleap, etc.)
        pose_estimation_desc (str): Pose estimation method description with the supported formats.
    """

    definition = """ 
    # Parameters used to obtain the keypoints data based on a specific pose estimation method.        
    format_method           : char(15)         # Supported pose estimation method (deeplabcut, sleap, anipose, sleap-anipose, nwb, facemap)
    ---
    pose_estimation_desc    : varchar(1000)    # Optional. Pose estimation method description with the supported formats.
    """

    contents = [
        ["deeplabcut", "`.csv` and `.h5/.hdf5` files generated by DeepLabcut analysis"],
        ["sleap", "`.slp` and `.h5/.hdf5` files generated by SLEAP analysis"],
        ["anipose", "`.csv` files generated by anipose analysis"],
        ["sleap-anipose", "`.h5/.hdf5` files generated by sleap-anipose analysis"],
        ["nwb", "`.nwb` files with Neurodata Without Borders (NWB) format"],
        ["facemap", "`.h5` files generated by Facemap analysis"],
    ]


@schema
class KeypointSet(dj.Manual):
    """Table to store the keypoint data and video set directory to train the model.

    Attributes:
        kpset_id (int): Unique ID for each keypoint set.
        PoseEstimationMethod (foreign key): Unique format method varchar used to obtain the keypoints data.
        kpset_config_dir (str): Path relative to root data directory where the config file is located.
        kpset_videos_dir (str): Path relative to root data directory where the videos and their keypoints are located.
        kpset_desc (str): Optional. User-entered description.
    """

    definition = """
    kpset_id                        : int           # Unique ID for each keypoint set   
    ---
    -> PoseEstimationMethod                         # Unique format method used to obtain the keypoints data
    kpset_config_dir                : varchar(255)  # Path relative to root data directory where the config file is located
    kpset_videos_dir                : varchar(255)  # Path relative to root data directory where the videos and their keypoints are located
    kpset_desc=''                   : varchar(300)  # Optional. User-entered description
    """

    class VideoFile(dj.Part):
        """IDs and file paths of each video file that will be used to train the model.

        Attributes:
            video_id (int): Unique ID for each video.
            video_path (str): Filepath of each video, relative to root data directory.
        """

        definition = """
        -> master
        video_id                    : int           # Unique ID for each video
        ---
        video_path                  : varchar(1000) # Filepath of each video, relative to root data directory
        """


@schema
class Bodyparts(dj.Manual):
    """Table to store the body parts to use in the analysis.

    Attributes:
        KeypointSet (foreign key)       : Unique ID for each keypoint set.
        bodyparts_id (int)              : Unique ID for a set of bodyparts for a particular keypoint set.
        anterior_bodyparts (blob)       : List of strings of anterior bodyparts
        posterior_bodyparts (blob)      : List of strings of posterior bodyparts
        use_bodyparts (blob)            : List of strings of bodyparts to be used
        bodyparts_desc(varchar)         : Optional. User-entered description.
    """

    definition = """
    -> KeypointSet                              # Unique ID for each keypoint set
    bodyparts_id                : int           # Unique ID for a set of bodyparts for a particular keypoint set
    ---
    anterior_bodyparts          : blob          # List of strings of anterior bodyparts
    posterior_bodyparts         : blob          # List of strings of posterior bodyparts
    use_bodyparts               : blob          # List of strings of bodyparts to be used
    bodyparts_desc=''           : varchar(1000) # Optional. User-entered description
    """


@schema
class PCATask(dj.Manual):
    """
    Staging table to define the PCA task and its output directory.

    Attributes:
        Bodyparts (foreign key)         : Bodyparts Key
        kpms_project_output_dir (str)   : KPMS's output directory relative to root
    """

    definition = """ 
    -> Bodyparts                                        # Unique ID for each Bodyparts key
    ---
    kpms_project_output_dir=''          : varchar(255)  # KPMS's output directory relative to root
    """


@schema
class PCAPrep(dj.Imported):
    """
    Table to create the `kpms_project_output_dir`, and create and update the `config.yml` by creating a new `kpms_dj_config.yml`.

    Attributes:
        PCATask (foreign key)           : Unique ID for each PCATask.
        coordinates (longblob)          : Dictionary mapping filenames to keypoint coordinates as ndarrays of shape (n_frames, n_bodyparts, 2[or 3])
        confidences (longblob)          : Dictionary mapping filenames to `likelihood` scores as ndarrays of shape (n_frames, n_bodyparts)
        formatted_bodyparts (longblob)  : List of bodypart names. The order of the names matches the order of the bodyparts in `coordinates` and `confidences`.
        average_frame_rate (float0      : Average frame rate of the trained videos
        frame_rates (longblob)          : List of frame rates of the trained videos
    """

    definition = """
    -> PCATask                          # Unique ID for each PCATask
    ---
    coordinates             : longblob  # Dictionary mapping filenames to keypoint coordinates as ndarrays of shape (n_frames, n_bodyparts, 2[or 3])
    confidences             : longblob  # Dictionary mapping filenames to `likelihood` scores as ndarrays of shape (n_frames, n_bodyparts)           
    formatted_bodyparts     : longblob  # List of bodypart names. The order of the names matches the order of the bodyparts in `coordinates` and `confidences`.
    average_frame_rate      : float     # Average frame rate of the trained videos
    frame_rates             : longblob  # List of frame rates of the trained videos
    """

    def make(self, key):
        """
        Make function to:
        1. Generate and update the `kpms_dj_config.yml` with both the `video_dir` and the bodyparts.
        2. Create the keypoint coordinates and confidences scores to format the data for the PCA fitting.

        Args:
            key (dict): Primary key from the PCATask table.

        Raises:
            NotImplementedError: `format_method` is only supported for `deeplabcut`. If support required for another format method, reach out to us.

        High-Level Logic:
        1. Fetches the bodyparts, output_dir and keypoint method, and keypoint config and videoset directories.
        2. Creates the `kpms_project_output_dir` (if it does not exist), and generates the kpms default `config.yml` with the default values from the pose estimation (DLC) config.
        3. Create a copy of the kpms `config.yml` named `kpms_dj_config.yml` that will be updated with both the `video_dir` and bodyparts
        4. Calculate the `filepath_patterns` that will select the videos from `KeypointSet.VideoFile` as the training set.
        4. Load keypoint data for the selected training videoset. The coordinates and confidences scores will be used to format the data for modeling.
        5. Calculate the average frame rate of the videoset chosen to train the model. The average frame rate can be used to calculate the kappa value.
        6. Insert the results of this `make` function into the table.
        """

        anterior_bodyparts, posterior_bodyparts, use_bodyparts = (
            Bodyparts & key
        ).fetch1(
            "anterior_bodyparts",
            "posterior_bodyparts",
            "use_bodyparts",
        )
        kpms_project_output_dir = (PCATask & key).fetch1("kpms_project_output_dir")
        kpms_project_output_dir = (
            get_kpms_processed_data_dir() / kpms_project_output_dir
        )

        format_method, kpset_config_dir, kpset_videos_dir = (KeypointSet & key).fetch1(
            "format_method", "kpset_config_dir", "kpset_videos_dir"
        )

        file_paths, video_ids = (KeypointSet.VideoFile & key).fetch(
            "video_path", "video_id"
        )

        kpset_config_dir = find_full_path(get_kpms_root_data_dir(), kpset_config_dir)
        kpset_videos_dir = find_full_path(get_kpms_root_data_dir(), kpset_videos_dir)

        setup_project(
            kpms_project_output_dir, deeplabcut_config=kpset_config_dir / "config.yaml"
        )

        kpms_config = load_config(
            kpms_project_output_dir.as_posix(), check_if_valid=True, build_indexes=False
        )

        kpms_dj_config_kwargs_dict = dict(
            video_dir=kpset_videos_dir.as_posix(),
            anterior_bodyparts=anterior_bodyparts,
            posterior_bodyparts=posterior_bodyparts,
            use_bodyparts=use_bodyparts,
        )
        kpms_config.update(**kpms_dj_config_kwargs_dict)
        generate_kpms_dj_config(kpms_project_output_dir.as_posix(), **kpms_config)

        filepath_patterns = [
            (
                kpset_videos_dir / (os.path.splitext(os.path.basename(path))[0] + "*")
            ).as_posix()
            for path in file_paths
        ]

        if format_method == "deeplabcut":
            coordinates, confidences, formatted_bodyparts = load_keypoints(
                filepath_pattern=filepath_patterns, format=format_method
            )
        else:
            raise NotImplementedError(
                "The currently supported format method is `deeplabcut`. If you require \
        support for another format method, please reach out to us at `support at datajoint.com`."
            )

        fps_list = []
        for fp, video_id in zip(file_paths, video_ids):
            file_path = (find_full_path(get_kpms_root_data_dir(), fp)).as_posix()
            cap = cv2.VideoCapture(file_path)
            fps_list.append(int(cap.get(cv2.CAP_PROP_FPS)))
            cap.release()
        average_frame_rate = int(np.mean(fps_list))

        self.insert1(
            dict(
                **key,
                coordinates=coordinates,
                confidences=confidences,
                formatted_bodyparts=formatted_bodyparts,
                average_frame_rate=average_frame_rate,
                frame_rates=fps_list,
            )
        )


@schema
class PCAFitting(dj.Computed):
    """Automated fitting of the PCA model.

    Attributes:
        PCAPrep (foreign key)           : PCAPrep Key.
        pca_fitting_time (datetime)     : datetime of the PCA fitting analysis.
    """

    definition = """
    -> PCAPrep                           # PCAPrep Key
    ---
    pca_fitting_time=NULL    : datetime  # datetime of the PCA fitting analysis
    """

    def make(self, key):
        """
        Make function to format the keypoint data, fit the PCA model, and store it as a `pca.p` file in the KPMS output directory.
        
        Args:
            key (dict): PCAPrep Key

        Raises:

        High-Level Logic:
        1. Fetch the `kpms_project_output_dir` from the PCATask table.
        2. Load the `kpms_dj_config` file that contains the updated `video_dir` and bodyparts, \
            and format the keypoint data with the coordinates and confidences scores to be used in the PCA fitting.
        3. Fit the PCA model and save it as `pca.p` file in the output directory.
        4.Insert the creation datetime as the `pca_fitting_time` into the table.
        """

        kpms_project_output_dir = (PCATask & key).fetch1("kpms_project_output_dir")
        kpms_project_output_dir = (
            get_kpms_processed_data_dir() / kpms_project_output_dir
        )

        from keypoint_moseq import format_data, fit_pca, save_pca

        kpms_default_config = load_kpms_dj_config(
            kpms_project_output_dir.as_posix(), check_if_valid=True, build_indexes=True
        )
        coordinates, confidences = (PCAPrep & key).fetch1(
            "coordinates", "confidences"
        )
        data, _ = format_data(
            **kpms_default_config, coordinates=coordinates, confidences=confidences
        )

        pca = fit_pca(**data, **kpms_default_config)
        save_pca(pca, kpms_project_output_dir.as_posix())

        creation_datetime = datetime.now(timezone.utc)
        self.insert1(dict(**key, pca_fitting_time=creation_datetime))


@schema
class LatentDimension(dj.Imported):
    """
    Automated computation to calculate the latent dimension as one of the autoregressive hyperparameters (`ar_hypparams`) \
    necessary for the model fitting.
    The analysis aims to select each of the components that explain the 90% of variance (fixed threshold).

    Attributes:
        PCAFitting (foreign key)           : PCAFitting Key.
        variance_percentage (float)        : Variance threshold. Fixed value to 90%.
        latent_dimension (int)             : Number of principal components required to explain the specified variance.
        latent_dim_desc (varchar)          : Automated description of the computation result.
    """

    definition = """
    -> PCAFitting                                   # PCAFitting Key
    ---
    variance_percentage      : float            # Variance threshold. Fixed value to 0.9
    latent_dimension         : int              # Number of principal components required to explain the specified variance.
    latent_dim_desc          : varchar(1000)    # Automated description of the computation result.
    """

    def make(self, key):
        """
        Make function to compute and store the latent dimensions that explain a 90% variance threshold.

        Args:
            key (dict): PCAFitting Key.

        Raises:

        High-Level Logic:
        1. Fetches the output directory from the PCATask table and load the PCA model from the output directory.
        2. Set a specified variance threshold to 90% and compute the cumulative sum of the explained variance ratio.
        3. Determine the number of components required to explain the specified variance.
            3.1 If the cumulative sum of the explained variance ratio is less than the specified variance threshold, \
                it sets the `latent_dimension` to the total number of components and `variance_percentage` to the cumulative sum of the explained variance ratio.
            3.2 If the cumulative sum of the explained variance ratio is greater than the specified variance threshold, \
                it sets the `latent_dimension` to the number of components that explain the specified variance and `variance_percentage` to the specified variance threshold.
        4. Insert the results of this `make` function into the table.
        """
        from keypoint_moseq import load_pca

        kpms_project_output_dir = (PCATask & key).fetch1("kpms_project_output_dir")
        kpms_project_output_dir = (
            get_kpms_processed_data_dir() / kpms_project_output_dir
        )

        pca = load_pca(kpms_project_output_dir.as_posix())

        variance_threshold = 0.90
        cs = np.cumsum(
            pca.explained_variance_ratio_
        )  # explained_variance_ratio_ndarray of shape (n_components,)

        if cs[-1] < variance_threshold:
            latent_dimension = len(cs)
            variance_percentage = cs[-1] * 100
            latent_dim_desc = (
                f"All components together only explain {cs[-1]*100}% of variance."
            )
        else:
            latent_dimension = (cs > variance_threshold).nonzero()[0].min() + 1
            variance_percentage = variance_threshold * 100
            latent_dim_desc = f">={variance_threshold*100}% of variance explained by {(cs>variance_threshold).nonzero()[0].min()+1} components."

        self.insert1(
            dict(
                **key,
                variance_percentage=variance_percentage,
                latent_dimension=latent_dimension,
                latent_dim_desc=latent_dim_desc,
            )
        )
