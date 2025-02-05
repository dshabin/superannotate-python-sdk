import concurrent.futures
import logging
import os.path
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Iterable
from typing import List

import boto3
import lib.core as constances
import pandas as pd
import requests
from botocore.exceptions import ClientError
from lib.app.analytics.common import aggregate_image_annotations_as_df
from lib.app.analytics.common import consensus_plot
from lib.app.analytics.common import image_consensus
from lib.core.conditions import Condition
from lib.core.conditions import CONDITION_EQ as EQ
from lib.core.entities import FolderEntity
from lib.core.entities import MLModelEntity
from lib.core.entities import ProjectEntity
from lib.core.enums import ExportStatus
from lib.core.enums import ProjectType
from lib.core.exceptions import AppException
from lib.core.exceptions import AppValidationException
from lib.core.repositories import BaseManageableRepository
from lib.core.repositories import BaseReadOnlyRepository
from lib.core.serviceproviders import SuerannotateServiceProvider
from lib.core.usecases.base import BaseInteractiveUseCase
from lib.core.usecases.base import BaseUseCase
from lib.core.usecases.images import GetBulkImages


logger = logging.getLogger("root")


class PrepareExportUseCase(BaseUseCase):
    def __init__(
        self,
        project: ProjectEntity,
        folder_names: List[str],
        backend_service_provider: SuerannotateServiceProvider,
        include_fuse: bool,
        only_pinned: bool,
        annotation_statuses: List[str] = None,
    ):
        super().__init__(),
        self._project = project
        self._folder_names = list(folder_names) if folder_names else None
        self._backend_service = backend_service_provider
        self._annotation_statuses = annotation_statuses
        self._include_fuse = include_fuse
        self._only_pinned = only_pinned

    def validate_only_pinned(self):
        if (
            self._project.upload_state == constances.UploadState.EXTERNAL.value
            and self._only_pinned
        ):
            raise AppValidationException(
                f"Pin functionality is not supported for  projects containing {self._project.project_type} attached with URLs"
            )

    def validate_fuse(self):
        if (
            self._project.upload_state == constances.UploadState.EXTERNAL.value
            and self._include_fuse
        ):
            raise AppValidationException(
                f"Include fuse functionality is not supported for  projects containing {self._project.project_type} attached with URLs"
            )

    def execute(self):
        if self.is_valid():
            if self._project.upload_state == constances.UploadState.EXTERNAL.value:
                self._include_fuse = False

            if not self._annotation_statuses:
                self._annotation_statuses = (
                    constances.AnnotationStatus.IN_PROGRESS.name,
                    constances.AnnotationStatus.COMPLETED.name,
                    constances.AnnotationStatus.QUALITY_CHECK.name,
                    constances.AnnotationStatus.RETURNED.name,
                    constances.AnnotationStatus.NOT_STARTED.name,
                    constances.AnnotationStatus.SKIPPED.name,
                )

            response = self._backend_service.prepare_export(
                project_id=self._project.uuid,
                team_id=self._project.team_id,
                folders=self._folder_names,
                annotation_statuses=self._annotation_statuses,
                include_fuse=self._include_fuse,
                only_pinned=self._only_pinned,
            )
            if "error" in response:
                raise AppException(response["error"])

            report_message = ""
            if self._folder_names:
                report_message = f"[{', '.join(self._folder_names)}] "
            logger.info(
                f"Prepared export {response['name']} for project {self._project.name} "
                f"{report_message}(project ID {self._project.uuid})."
            )
            self._response.data = response

        return self._response


class GetExportsUseCase(BaseUseCase):
    def __init__(
        self,
        service: SuerannotateServiceProvider,
        project: ProjectEntity,
        return_metadata: bool = False,
    ):
        super().__init__()
        self._service = service
        self._project = project
        self._return_metadata = return_metadata

    def execute(self):
        if self.is_valid():
            data = self._service.get_exports(
                team_id=self._project.team_id, project_id=self._project.uuid
            )
            self._response.data = data
            if not self._return_metadata:
                self._response.data = [i["name"] for i in data]
        return self._response


class CreateModelUseCase(BaseUseCase):
    def __init__(
        self,
        base_model_name: str,
        model_name: str,
        model_description: str,
        task: str,
        team_id: int,
        train_data_paths: Iterable[str],
        test_data_paths: Iterable[str],
        backend_service_provider: SuerannotateServiceProvider,
        projects: BaseReadOnlyRepository,
        folders: BaseReadOnlyRepository,
        ml_models: BaseManageableRepository,
        hyper_parameters: dict = None,
    ):
        super().__init__()
        self._base_model_name = base_model_name
        self._model_name = model_name
        self._model_description = model_description
        self._task = task
        self._team_id = team_id
        self._hyper_parameters = hyper_parameters
        self._train_data_paths = train_data_paths
        self._test_data_paths = test_data_paths
        self._backend_service = backend_service_provider
        self._ml_models = ml_models
        self._projects = projects
        self._folders = folders

    @property
    def hyper_parameters(self):
        if self._hyper_parameters:
            for parameter in constances.DEFAULT_HYPER_PARAMETERS:
                if parameter not in self._hyper_parameters:
                    self._hyper_parameters[
                        parameter
                    ] = constances.DEFAULT_HYPER_PARAMETERS[parameter]
        else:
            self._hyper_parameters = constances.DEFAULT_HYPER_PARAMETERS
        return self._hyper_parameters

    @staticmethod
    def split_path(path: str):
        if "/" in path:
            return path.split("/")
        return path, "root"

    def execute(self):
        train_folder_ids = []
        test_folder_ids = []
        projects = []

        for path in self._train_data_paths:
            project_name, folder_name = self.split_path(path)
            projects = self._projects.get_all(
                Condition("name", project_name, EQ)
                & Condition("team_id", self._team_id, EQ)
            )

            projects.extend(projects)
            folders = self._folders.get_all(
                Condition("name", folder_name, EQ)
                & Condition("team_id", self._team_id, EQ)
                & Condition("project_id", projects[0].uuid, EQ)
            )
            train_folder_ids.append(folders[0].uuid)

        for path in self._test_data_paths:
            project_name, folder_name = self.split_path(path)
            projects.extend(
                self._projects.get_all(
                    Condition("name", project_name, EQ)
                    & Condition("team_id", self._team_id, EQ)
                )
            )
            folders = self._folders.get_all(
                Condition("name", folder_name, EQ)
                & Condition("team_id", self._team_id, EQ)
                & Condition("project_id", projects[0].uuid, EQ)
            )
            test_folder_ids.append(folders[0].uuid)

        project_types = [project.project_type for project in projects]

        if set(train_folder_ids) & set(test_folder_ids):
            self._response.errors = AppException(
                "Avoid overlapping between training and test data."
            )
            return
        if len(set(project_types)) != 1:
            self._response.errors = AppException(
                "All projects have to be of the same type. Either vector or pixel"
            )
            return
        if any(
            {
                True
                for project in projects
                if project.upload_state == constances.UploadState.EXTERNAL.value
            }
        ):
            self._response.errors = AppException(
                "The function does not support projects containing images attached with URLs"
            )
            return

        base_model = self._ml_models.get_all(
            Condition("name", self._base_model_name, EQ)
            & Condition("team_id", self._team_id, EQ)
            & Condition("task", constances.MODEL_TRAINING_TASKS[self._task], EQ)
            & Condition("type", project_types[0], EQ)
            & Condition("include_global", True, EQ)
        )[0]

        if base_model.model_type != project_types[0]:
            self._response.errors = AppException(
                f"The type of provided projects is {project_types[0]}, "
                "and does not correspond to the type of provided model"
            )
            return self._response

        completed_images_data = self._backend_service.bulk_get_folders(
            self._team_id, [project.uuid for project in projects]
        )
        complete_image_count = sum(
            [
                folder["completedCount"]
                for folder in completed_images_data["data"]
                if folder["id"] in train_folder_ids
            ]
        )
        ml_model = MLModelEntity(
            name=self._model_name,
            description=self._model_description,
            task=constances.MODEL_TRAINING_TASKS[self._task],
            base_model_id=base_model.uuid,
            image_count=complete_image_count,
            model_type=project_types[0],
            train_folder_ids=train_folder_ids,
            test_folder_ids=test_folder_ids,
            hyper_parameters=self.hyper_parameters,
        )
        new_model_data = self._ml_models.insert(ml_model)

        self._response.data = new_model_data
        return self._response


class GetModelMetricsUseCase(BaseUseCase):
    def __init__(
        self,
        model_id: int,
        team_id: int,
        backend_service_provider: SuerannotateServiceProvider,
    ):
        super().__init__()
        self._model_id = model_id
        self._team_id = team_id
        self._backend_service = backend_service_provider

    def execute(self):
        metrics = self._backend_service.get_model_metrics(
            team_id=self._team_id, model_id=self._model_id
        )
        self._response.data = metrics
        return self._response


class UpdateModelUseCase(BaseUseCase):
    def __init__(
        self, model: MLModelEntity, models: BaseManageableRepository,
    ):
        super().__init__()
        self._models = models
        self._model = model

    def execute(self):
        model = self._models.update(self._model)
        self._response.data = model
        return self._response


class DeleteMLModel(BaseUseCase):
    def __init__(self, model_id: int, models: BaseManageableRepository):
        super().__init__()
        self._model_id = model_id
        self._models = models

    def execute(self):
        self._response.data = self._models.delete(self._model_id)
        return self._response


class StopModelTraining(BaseUseCase):
    def __init__(
        self,
        model_id: int,
        team_id: int,
        backend_service_provider: SuerannotateServiceProvider,
    ):
        super().__init__()

        self._model_id = model_id
        self._team_id = team_id
        self._backend_service = backend_service_provider

    def execute(self):
        is_stopped = self._backend_service.stop_model_training(
            self._team_id, self._model_id
        )
        if not is_stopped:
            self._response.errors = AppException("Something went wrong.")
        return self._response


class DownloadExportUseCase(BaseInteractiveUseCase):
    def __init__(
        self,
        service: SuerannotateServiceProvider,
        project: ProjectEntity,
        export_name: str,
        folder_path: str,
        extract_zip_contents: bool,
        to_s3_bucket: bool,
    ):
        super().__init__()
        self._service = service
        self._project = project
        self._export_name = export_name
        self._folder_path = folder_path
        self._extract_zip_contents = extract_zip_contents
        self._to_s3_bucket = to_s3_bucket
        self._temp_dir = None

    def upload_to_s3_from_folder(self, folder_path: str):
        to_s3_bucket = boto3.Session().resource("s3").Bucket(self._to_s3_bucket)
        files_to_upload = list(Path(folder_path).rglob("*.*"))

        def _upload_file_to_s3(_to_s3_bucket, _path, _s3_key) -> None:
            _to_s3_bucket.upload_file(_path, _s3_key)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = []
            for path in files_to_upload:
                s3_key = f"{self._folder_path}/{path.name}"
                results.append(
                    executor.submit(_upload_file_to_s3, to_s3_bucket, str(path), s3_key)
                )
                yield

    def download_to_local_storage(self, destination: str):
        exports = self._service.get_exports(
            team_id=self._project.team_id, project_id=self._project.uuid
        )
        export = next(filter(lambda i: i["name"] == self._export_name, exports), None)
        export = self._service.get_export(
            team_id=self._project.team_id,
            project_id=self._project.uuid,
            export_id=export["id"],
        )
        if not export:
            raise AppException("Export not found.")
        export_status = export["status"]

        while export_status != ExportStatus.COMPLETE.value:
            logger.info("Waiting 5 seconds for export to finish on server.")
            time.sleep(5)

            export = self._service.get_export(
                team_id=self._project.team_id,
                project_id=self._project.uuid,
                export_id=export["id"],
            )
            if "error" in export:
                raise AppException(export["error"])
            export_status = export["status"]
            if export_status in (ExportStatus.ERROR.value, ExportStatus.CANCELED.value):
                raise AppException("Couldn't download export.")

        filename = Path(export["path"]).name
        filepath = Path(destination) / filename
        with requests.get(export["download"], stream=True) as response:
            response.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        if self._extract_zip_contents:
            with zipfile.ZipFile(filepath, "r") as f:
                f.extractall(destination)
            Path.unlink(filepath)
        return export["id"], filepath, destination

    def get_upload_files_count(self):
        if not self._temp_dir:
            self._temp_dir = tempfile.TemporaryDirectory()
            self.download_to_local_storage(self._temp_dir.name)
        return len(list(Path(self._temp_dir.name).rglob("*.*")))

    def execute(self):
        if self.is_valid():
            report = []
            if self._to_s3_bucket:
                self.get_upload_files_count()
                yield from self.upload_to_s3_from_folder(self._temp_dir.name)
                report.append(
                    f"Exported to AWS {self._to_s3_bucket}/{self._folder_path}"
                )
                self._temp_dir.cleanup()
            else:
                export_id, filepath, destination = self.download_to_local_storage(
                    self._folder_path
                )
                if self._extract_zip_contents:
                    report.append(f"Extracted {filepath} to folder {destination}")
                else:
                    report.append(f"Downloaded export ID {export_id} to {filepath}")
                yield
            self._response.data = "\n".join(report)
        return self._response


class DownloadMLModelUseCase(BaseUseCase):
    def __init__(
        self,
        model: MLModelEntity,
        download_path: str,
        backend_service_provider: SuerannotateServiceProvider,
        team_id: int,
    ):
        super().__init__()
        self._model = model
        self._download_path = download_path
        self._backend_service = backend_service_provider
        self._team_id = team_id

    def validate_training_status(self):
        if self._model.training_status not in [
            constances.TrainingStatus.COMPLETED.value,
            constances.TrainingStatus.FAILED_AFTER_EVALUATION_WITH_SAVE_MODEL.value,
        ]:
            raise AppException("Unable to download.")

    def execute(self):
        if self.is_valid():
            metrics_name = os.path.basename(self._model.path).replace(".pth", ".json")
            mapper_path = self._model.config_path.replace(
                os.path.basename(self._model.config_path), "classes_mapper.json"
            )
            metrics_path = self._model.config_path.replace(
                os.path.basename(self._model.config_path), metrics_name
            )

            auth_response = self._backend_service.get_ml_model_download_tokens(
                self._team_id, self._model.uuid
            )
            if not auth_response.ok:
                raise AppException(auth_response.error)
            s3_session = boto3.Session(
                aws_access_key_id=auth_response.data.access_key,
                aws_secret_access_key=auth_response.data.secret_key,
                aws_session_token=auth_response.data.session_token,
                region_name=auth_response.data.region,
            )
            bucket = s3_session.resource("s3").Bucket(auth_response.data.bucket)

            bucket.download_file(
                self._model.config_path,
                os.path.join(self._download_path, "config.yaml"),
            )
            bucket.download_file(
                self._model.path,
                os.path.join(self._download_path, os.path.basename(self._model.path)),
            )
            try:
                bucket.download_file(
                    metrics_path, os.path.join(self._download_path, metrics_name)
                )
                bucket.download_file(
                    mapper_path,
                    os.path.join(self._download_path, "classes_mapper.json"),
                )
            except ClientError:
                logger.info(
                    "The specified model does not contain a classes_mapper and/or a metrics file."
                )
            self._response.data = self._model
        return self._response


class BenchmarkUseCase(BaseUseCase):
    def __init__(
        self,
        project: ProjectEntity,
        ground_truth_folder_name: str,
        folder_names: list,
        export_dir: str,
        image_list: list,
        annotation_type: str,
        show_plots: bool,
    ):
        super().__init__()
        self._project = project
        self._ground_truth_folder_name = ground_truth_folder_name
        self._folder_names = folder_names
        self._export_dir = export_dir
        self._image_list = image_list
        self._annotation_type = annotation_type
        self._show_plots = show_plots

    def execute(self):
        project_df = aggregate_image_annotations_as_df(self._export_dir)
        gt_project_df = project_df[
            project_df["folderName"] == self._ground_truth_folder_name
        ]
        benchmark_dfs = []
        for folder_name in self._folder_names:
            folder_df = project_df[project_df["folderName"] == folder_name]
            project_gt_df = pd.concat([folder_df, gt_project_df])
            project_gt_df = project_gt_df[project_gt_df["instanceId"].notna()]

            if self._image_list is not None:
                project_gt_df = project_gt_df.loc[
                    project_gt_df["imageName"].isin(self._image_list)
                ]

            project_gt_df.query("type == '" + self._annotation_type + "'", inplace=True)

            project_gt_df = project_gt_df.groupby(
                ["imageName", "instanceId", "folderName"]
            )

            def aggregate_attributes(instance_df):
                def attribute_to_list(attribute_df):
                    attribute_names = list(attribute_df["attributeName"])
                    attribute_df["attributeNames"] = len(attribute_df) * [
                        attribute_names
                    ]
                    return attribute_df

                attributes = None
                if not instance_df["attributeGroupName"].isna().all():
                    attrib_group_name = instance_df.groupby("attributeGroupName")[
                        ["attributeGroupName", "attributeName"]
                    ].apply(attribute_to_list)
                    attributes = dict(
                        zip(
                            attrib_group_name["attributeGroupName"],
                            attrib_group_name["attributeNames"],
                        )
                    )

                instance_df.drop(
                    ["attributeGroupName", "attributeName"], axis=1, inplace=True
                )
                instance_df.drop_duplicates(
                    subset=["imageName", "instanceId", "folderName"], inplace=True
                )
                instance_df["attributes"] = [attributes]
                return instance_df

            project_gt_df = project_gt_df.apply(aggregate_attributes).reset_index(
                drop=True
            )
            unique_images = set(project_gt_df["imageName"])
            all_benchmark_data = []
            for image_name in unique_images:
                image_data = image_consensus(
                    project_gt_df, image_name, self._annotation_type
                )
                all_benchmark_data.append(pd.DataFrame(image_data))
            benchmark_project_df = pd.concat(all_benchmark_data, ignore_index=True)
            benchmark_project_df = benchmark_project_df[
                benchmark_project_df["folderName"] == folder_name
            ]
            benchmark_dfs.append(benchmark_project_df)
        benchmark_df = pd.concat(benchmark_dfs, ignore_index=True)
        if self._show_plots:
            consensus_plot(benchmark_df, self._folder_names)
        self._response.data = benchmark_df
        return self._response


class ConsensusUseCase(BaseUseCase):
    def __init__(
        self,
        project: ProjectEntity,
        folder_names: list,
        export_dir: str,
        image_list: list,
        annotation_type: str,
        show_plots: bool,
    ):
        super().__init__()
        self._project = project
        self._folder_names = folder_names
        self._export_dir = export_dir
        self._image_list = image_list
        self._annota_type_type = annotation_type
        self._show_plots = show_plots

    def execute(self):
        project_df = aggregate_image_annotations_as_df(self._export_dir)
        all_projects_df = project_df[project_df["instanceId"].notna()]
        all_projects_df = all_projects_df.loc[
            all_projects_df["folderName"].isin(self._folder_names)
        ]

        if self._image_list is not None:
            all_projects_df = all_projects_df.loc[
                all_projects_df["imageName"].isin(self._image_list)
            ]

        all_projects_df.query("type == '" + self._annota_type_type + "'", inplace=True)

        def aggregate_attributes(instance_df):
            def attribute_to_list(attribute_df):
                attribute_names = list(attribute_df["attributeName"])
                attribute_df["attributeNames"] = len(attribute_df) * [attribute_names]
                return attribute_df

            attributes = None
            if not instance_df["attributeGroupName"].isna().all():
                attrib_group_name = instance_df.groupby("attributeGroupName")[
                    ["attributeGroupName", "attributeName"]
                ].apply(attribute_to_list)
                attributes = dict(
                    zip(
                        attrib_group_name["attributeGroupName"],
                        attrib_group_name["attributeNames"],
                    )
                )

            instance_df.drop(
                ["attributeGroupName", "attributeName"], axis=1, inplace=True
            )
            instance_df.drop_duplicates(
                subset=["imageName", "instanceId", "folderName"], inplace=True
            )
            instance_df["attributes"] = [attributes]
            return instance_df

        all_projects_df = all_projects_df.groupby(
            ["imageName", "instanceId", "folderName"]
        )
        all_projects_df = all_projects_df.apply(aggregate_attributes).reset_index(
            drop=True
        )
        unique_images = set(all_projects_df["imageName"])
        all_consensus_data = []
        for image_name in unique_images:
            image_data = image_consensus(
                all_projects_df, image_name, self._annota_type_type
            )
            all_consensus_data.append(pd.DataFrame(image_data))

        consensus_df = pd.concat(all_consensus_data, ignore_index=True)

        if self._show_plots:
            consensus_plot(consensus_df, self._folder_names)

        self._response.data = consensus_df
        return self._response


class RunSegmentationUseCase(BaseUseCase):
    def __init__(
        self,
        project: ProjectEntity,
        ml_model_repo: BaseManageableRepository,
        ml_model_name: str,
        images_list: list,
        service: SuerannotateServiceProvider,
        folder: FolderEntity,
    ):
        super().__init__()
        self._project = project
        self._ml_model_repo = ml_model_repo
        self._ml_model_name = ml_model_name
        self._images_list = images_list
        self._service = service
        self._folder = folder

    def validate_project_type(self):
        if self._project.project_type is not ProjectType.PIXEL.value:
            raise AppValidationException(
                "Operation not supported for given project type"
            )

    def validate_model(self):
        if self._ml_model_name not in constances.AVAILABLE_SEGMENTATION_MODELS:
            raise AppValidationException("Model Does not exist")

    def validate_upload_state(self):

        if self._project.upload_state is constances.UploadState.EXTERNAL:
            raise AppValidationException(
                "The function does not support projects containing images attached with URLs"
            )

    def execute(self):
        if self.is_valid():
            images = (
                GetBulkImages(
                    service=self._service,
                    project_id=self._project.uuid,
                    team_id=self._project.team_id,
                    folder_id=self._folder.uuid,
                    images=self._images_list,
                )
                .execute()
                .data
            )

            image_ids = [image.uuid for image in images]
            image_names = [image.name for image in images]

            if not len(image_names):
                self._response.errors = AppException(
                    "No valid image names were provided."
                )
                return self._response

            res = self._service.run_segmentation(
                self._project.team_id,
                self._project.uuid,
                model_name=self._ml_model_name,
                image_ids=image_ids,
            )
            if not res.ok:
                res.raise_for_status()

            success_images = []
            failed_images = []
            while len(success_images) + len(failed_images) != len(image_ids):
                images_metadata = (
                    GetBulkImages(
                        service=self._service,
                        project_id=self._project.uuid,
                        team_id=self._project.team_id,
                        folder_id=self._folder.uuid,
                        images=self._images_list,
                    )
                    .execute()
                    .data
                )

                success_images = [
                    img.name
                    for img in images_metadata
                    if img.segmentation_status
                    == constances.SegmentationStatus.COMPLETED.value
                ]
                failed_images = [
                    img.name
                    for img in images_metadata
                    if img.segmentation_status
                    == constances.SegmentationStatus.FAILED.value
                ]
                logger.info(
                    f"segmentation complete on {len(success_images + failed_images)} / {len(image_ids)} images"
                )
                time.sleep(5)

            self._response.data = (success_images, failed_images)
        return self._response


class RunPredictionUseCase(BaseUseCase):
    def __init__(
        self,
        project: ProjectEntity,
        ml_model_repo: BaseManageableRepository,
        ml_model_name: str,
        images_list: list,
        service: SuerannotateServiceProvider,
        folder: FolderEntity,
    ):
        super().__init__()
        self._project = project
        self._ml_model_repo = ml_model_repo
        self._ml_model_name = ml_model_name
        self._images_list = images_list
        self._service = service
        self._folder = folder

    def validate_project_type(self):
        if self._project.project_type in constances.LIMITED_FUNCTIONS:
            raise AppValidationException(
                constances.LIMITED_FUNCTIONS[self._project.project_type]
            )

    def execute(self):
        if self.is_valid():
            images = (
                GetBulkImages(
                    service=self._service,
                    project_id=self._project.uuid,
                    team_id=self._project.team_id,
                    folder_id=self._folder.uuid,
                    images=self._images_list,
                )
                .execute()
                .data
            )

            image_ids = [image.uuid for image in images]
            image_names = [image.name for image in images]

            if not len(image_names):
                self._response.errors = AppException(
                    "No valid image names were provided."
                )
                return self._response

            ml_models = self._ml_model_repo.get_all(
                condition=Condition("name", self._ml_model_name, EQ)
                & Condition("include_global", True, EQ)
                & Condition("team_id", self._project.team_id, EQ)
            )
            ml_model = None
            for model in ml_models:
                if model.name == self._ml_model_name:
                    ml_model = model

            res = self._service.run_prediction(
                team_id=self._project.team_id,
                project_id=self._project.uuid,
                ml_model_id=ml_model.uuid,
                image_ids=image_ids,
            )
            if not res.ok:
                return self._response

            success_images = []
            failed_images = []
            while len(success_images) + len(failed_images) != len(image_ids):
                images_metadata = (
                    GetBulkImages(
                        service=self._service,
                        project_id=self._project.uuid,
                        team_id=self._project.team_id,
                        folder_id=self._folder.uuid,
                        images=self._images_list,
                    )
                    .execute()
                    .data
                )

                success_images = [
                    img.name
                    for img in images_metadata
                    if img.prediction_status
                    == constances.SegmentationStatus.COMPLETED.value
                ]
                failed_images = [
                    img.name
                    for img in images_metadata
                    if img.prediction_status
                    == constances.SegmentationStatus.FAILED.value
                ]

                complete_images = success_images + failed_images
                logger.info(
                    f"prediction complete on {len(complete_images)} / {len(image_ids)} images"
                )
                time.sleep(5)

            self._response.data = (success_images, failed_images)
        return self._response


class SearchMLModels(BaseUseCase):
    def __init__(
        self, ml_models_repo: BaseManageableRepository, condition: Condition,
    ):
        super().__init__()
        self._ml_models = ml_models_repo
        self._condition = condition

    def execute(self):
        ml_models = self._ml_models.get_all(condition=self._condition)
        ml_models = [ml_model.to_dict() for ml_model in ml_models]
        self._response.data = ml_models
        return self._response
