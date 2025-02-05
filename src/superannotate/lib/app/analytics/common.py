import json
import logging
from pathlib import Path

import pandas as pd
import plotly.express as px
from lib.app.exceptions import AppException
from lib.core import DEPRICATED_DOCUMENT_VIDEO_MESSAGE


logger = logging.getLogger("root")


def df_to_annotations(df, output_dir):
    """Converts and saves pandas DataFrame annotation info (see aggregate_annotations_as_df)
    in output_dir.
    The DataFrame should have columns: "imageName", "className", "attributeGroupName",
    "attributeName", "type", "error", "locked", "visible", trackingId", "probability",
    "pointLabels", "meta", "commentResolved", "classColor", "groupId"

    Currently only works for Vector projects.

    :param df: pandas DataFrame of annotations possibly created by aggregate_annotations_as_df
    :type df: pandas.DataFrame
    :param output_dir: output dir for annotations and classes.json
    :type output_dir: str or Pathlike

    """

    project_suffix = "objects.json"
    images = df["imageName"].dropna().unique()
    for image in images:
        image_status = None
        image_pinned = None
        image_height = None
        image_width = None
        image_df = df[df["imageName"] == image]
        image_annotation = {"instances": [], "metadata": {}, "tags": [], "comments": []}
        instances = image_df["instanceId"].dropna().unique()
        for instance in instances:
            instance_df = image_df[image_df["instanceId"] == instance]
            # print(instance_df["instanceId"])
            annotation_type = instance_df.iloc[0]["type"]
            annotation_meta = instance_df.iloc[0]["meta"]

            instance_annotation = {
                "className": instance_df.iloc[0]["className"],
                "type": annotation_type,
                "attributes": [],
                "probability": instance_df.iloc[0]["probability"],
                "error": instance_df.iloc[0]["error"],
            }
            point_labels = instance_df.iloc[0]["pointLabels"]
            if point_labels is None:
                point_labels = []
            instance_annotation["pointLabels"] = point_labels
            instance_annotation["locked"] = bool(instance_df.iloc[0]["locked"])
            instance_annotation["visible"] = bool(instance_df.iloc[0]["visible"])
            instance_annotation["trackingId"] = instance_df.iloc[0]["trackingId"]
            instance_annotation["groupId"] = int(instance_df.iloc[0]["groupId"])
            instance_annotation.update(annotation_meta)
            for _, row in instance_df.iterrows():
                if row["attributeGroupName"] is not None:
                    instance_annotation["attributes"].append(
                        {
                            "groupName": row["attributeGroupName"],
                            "name": row["attributeName"],
                        }
                    )
            image_annotation["instances"].append(instance_annotation)
            image_width = image_width or instance_df.iloc[0]["imageWidth"]
            image_height = image_height or instance_df.iloc[0]["imageHeight"]
            image_pinned = image_pinned or instance_df.iloc[0]["imagePinned"]
            image_status = image_status or instance_df.iloc[0]["imageStatus"]

        comments = image_df[image_df["type"] == "comment"]
        for _, comment in comments.iterrows():
            comment_json = {}
            comment_json.update(comment["meta"])
            comment_json["correspondence"] = comment_json["comments"]
            del comment_json["comments"]
            comment_json["resolved"] = comment["commentResolved"]
            image_annotation["comments"].append(comment_json)

        tags = image_df[image_df["type"] == "tag"]
        for _, tag in tags.iterrows():
            image_annotation["tags"].append(tag["tag"])

        image_annotation["metadata"] = {
            "width": int(image_width),
            "height": int(image_height),
            "status": image_status,
            "pinned": bool(image_pinned),
        }
        json.dump(
            image_annotation,
            open(output_dir / f"{image}___{project_suffix}", "w"),
            indent=4,
        )

    annotation_classes = []
    for _, row in df.iterrows():
        if row["className"] is None:
            continue
        for annotation_class in annotation_classes:
            if annotation_class["name"] == row["className"]:
                break
        else:
            annotation_classes.append(
                {
                    "name": row["className"],
                    "color": row["classColor"],
                    "attribute_groups": [],
                }
            )
            annotation_class = annotation_classes[-1]
        if row["attributeGroupName"] is None or row["attributeName"] is None:
            continue
        for attribute_group in annotation_class["attribute_groups"]:
            if attribute_group["name"] == row["attributeGroupName"]:
                break
        else:
            annotation_class["attribute_groups"].append(
                {"name": row["attributeGroupName"], "attributes": []}
            )
            attribute_group = annotation_class["attribute_groups"][-1]
        for attribute in attribute_group["attributes"]:
            if attribute["name"] == row["attributeName"]:
                break
        else:
            attribute_group["attributes"].append({"name": row["attributeName"]})

    Path(output_dir / "classes").mkdir(exist_ok=True)
    json.dump(
        annotation_classes, open(output_dir / "classes" / "classes.json", "w"), indent=4
    )


def aggregate_image_annotations_as_df(
    project_root,
    include_classes_wo_annotations=False,
    include_comments=False,
    include_tags=False,
    folder_names=None,
):
    """Aggregate annotations as pandas dataframe from project root.

    :param project_root: export path of the project
    :type project_root: Pathlike (str or Path)
    :param include_classes_wo_annotations: enables inclusion of classes info
                                           that have no instances in annotations
    :type include_classes_wo_annotations: bool
    :param include_comments: enables inclusion of comments info as commentResolved column
    :type include_comments: bool
    :param include_tags: enables inclusion of tags info as tag column
    :type include_tags: bool
    :param folder_names: Aggregate the specified folders from project_root.
                                If None aggregate all folders in the project_root.
    :type folder_names: (list of str)

    :return: DataFrame on annotations with columns:
                                        "imageName", "instanceId",
                                        "className", "attributeGroupName", "attributeName", "type", "error", "locked",
                                        "visible", "trackingId", "probability", "pointLabels",
                                        "meta" (geometry information as string), "commentResolved", "classColor",
                                        "groupId", "imageWidth", "imageHeight", "imageStatus", "imagePinned",
                                        "createdAt", "creatorRole", "creationType", "creatorEmail", "updatedAt",
                                        "updatorRole", "updatorEmail", "tag", "folderName"
    :rtype: pandas DataFrame
    """

    json_paths = list(Path(str(project_root)).glob("*.json"))
    if (
        json_paths
        and "___pixel.json" not in json_paths[0].name
        and "___objects.json" not in json_paths[0].name
    ):
        raise AppException(DEPRICATED_DOCUMENT_VIDEO_MESSAGE)

    logger.info("Aggregating annotations from %s as pandas DataFrame", project_root)

    annotation_data = {
        "imageName": [],
        "imageHeight": [],
        "imageWidth": [],
        "imageStatus": [],
        "imagePinned": [],
        "instanceId": [],
        "className": [],
        "attributeGroupName": [],
        "attributeName": [],
        "type": [],
        "error": [],
        "locked": [],
        "visible": [],
        "trackingId": [],
        "probability": [],
        "pointLabels": [],
        "meta": [],
        "classColor": [],
        "groupId": [],
        "createdAt": [],
        "creatorRole": [],
        "creationType": [],
        "creatorEmail": [],
        "updatedAt": [],
        "updatorRole": [],
        "updatorEmail": [],
        "folderName": [],
        "imageAnnotator": [],
        "imageQA": [],
    }

    if include_comments:
        annotation_data["commentResolved"] = []
    if include_tags:
        annotation_data["tag"] = []

    classes_path = Path(project_root) / "classes" / "classes.json"
    if not classes_path.is_file():
        raise AppException(
            "SuperAnnotate classes file "
            + str(classes_path)
            + " not found. Please provide correct project export root"
        )
    classes_json = json.load(open(classes_path))
    class_name_to_color = {}
    class_group_name_to_values = {}
    for annotation_class in classes_json:
        name = annotation_class["name"]
        color = annotation_class["color"]
        class_name_to_color[name] = color
        class_group_name_to_values[name] = {}
        for attribute_group in annotation_class["attribute_groups"]:
            class_group_name_to_values[name][attribute_group["name"]] = []
            for attribute in attribute_group["attributes"]:
                class_group_name_to_values[name][attribute_group["name"]].append(
                    attribute["name"]
                )

    def __append_annotation(annotation_dict):
        for annotation_key in annotation_data:
            if annotation_key in annotation_dict:
                annotation_data[annotation_key].append(annotation_dict[annotation_key])
            else:
                annotation_data[annotation_key].append(None)

    def __get_image_metadata(image_name, annotations):
        image_metadata = {"imageName": image_name}

        image_metadata["imageHeight"] = annotations["metadata"].get("height")
        image_metadata["imageWidth"] = annotations["metadata"].get("width")
        image_metadata["imageStatus"] = annotations["metadata"].get("status")
        image_metadata["imagePinned"] = annotations["metadata"].get("pinned")
        image_metadata["imageAnnotator"] = annotations["metadata"].get("annotatorEmail")
        image_metadata["imageQA"] = annotations["metadata"].get("qaEmail")
        return image_metadata

    def __get_user_metadata(annotation):
        annotation_created_at = pd.to_datetime(annotation.get("createdAt"))
        annotation_created_by = annotation.get("createdBy")
        annotation_creator_email = None
        annotation_creator_role = None
        if annotation_created_by:
            annotation_creator_email = annotation_created_by.get("email")
            annotation_creator_role = annotation_created_by.get("role")
        annotation_creation_type = annotation.get("creationType")
        annotation_updated_at = pd.to_datetime(annotation.get("updatedAt"))
        annotation_updated_by = annotation.get("updatedBy")
        annotation_updator_email = None
        annotation_updator_role = None
        if annotation_updated_by:
            annotation_updator_email = annotation_updated_by.get("email")
            annotation_updator_role = annotation_updated_by.get("role")
        user_metadata = {
            "createdAt": annotation_created_at,
            "creatorRole": annotation_creator_role,
            "creatorEmail": annotation_creator_email,
            "creationType": annotation_creation_type,
            "updatedAt": annotation_updated_at,
            "updatorRole": annotation_updator_role,
            "updatorEmail": annotation_updator_email,
        }
        return user_metadata

    annotations_paths = []

    if folder_names is None:
        project_dir_content = Path(project_root).glob("*")
        for entry in project_dir_content:
            if entry.is_file() and entry.suffix == ".json":
                annotations_paths.append(entry)
            elif entry.is_dir() and entry.name != "classes":
                annotations_paths.extend(list(entry.rglob("*.json")))
    else:
        for folder_name in folder_names:
            annotations_paths.extend(
                list((Path(project_root) / folder_name).rglob("*.json"))
            )

    if not annotations_paths:
        logger.warning(f"Could not find annotations in {project_root}.")
    if len(list(Path(project_root).rglob("*___objects.json"))) > 0:
        type_postfix = "___objects.json"
    else:
        type_postfix = "___pixel.json"
    for annotation_path in annotations_paths:
        annotation_json = json.load(open(annotation_path))
        parts = annotation_path.name.split(type_postfix)
        if len(parts) != 2:
            continue
        image_name = parts[0]
        image_metadata = __get_image_metadata(image_name, annotation_json)
        annotation_instance_id = 0
        if include_comments:
            for annotation in annotation_json["comments"]:
                comment_resolved = annotation["resolved"]
                comment_meta = {
                    "x": annotation["x"],
                    "y": annotation["y"],
                    "comments": annotation["correspondence"],
                }
                annotation_dict = {
                    "type": "comment",
                    "meta": comment_meta,
                    "commentResolved": comment_resolved,
                }
                user_metadata = __get_user_metadata(annotation)
                annotation_dict.update(user_metadata)
                annotation_dict.update(image_metadata)
                __append_annotation(annotation_dict)
        if include_tags:
            for annotation in annotation_json["tags"]:
                annotation_dict = {"type": "tag", "tag": annotation}
                annotation_dict.update(image_metadata)
                __append_annotation(annotation_dict)
        for annotation in annotation_json["instances"]:
            annotation_type = annotation.get("type", "mask")
            annotation_class_name = annotation.get("className")
            if (
                annotation_class_name is None
                or annotation_class_name not in class_name_to_color
            ):
                logger.warning(
                    "Annotation class %s not found in classes json. Skipping.",
                    annotation_class_name,
                )
                continue
            annotation_class_color = class_name_to_color[annotation_class_name]
            annotation_group_id = annotation.get("groupId")
            annotation_locked = annotation.get("locked")
            annotation_visible = annotation.get("visible")
            annotation_tracking_id = annotation.get("trackingId")
            annotation_meta = None
            if annotation_type in ["bbox", "polygon", "polyline", "cuboid"]:
                annotation_meta = {"points": annotation["points"]}
            elif annotation_type == "point":
                annotation_meta = {"x": annotation["x"], "y": annotation["y"]}
            elif annotation_type == "ellipse":
                annotation_meta = {
                    "cx": annotation["cx"],
                    "cy": annotation["cy"],
                    "rx": annotation["rx"],
                    "ry": annotation["ry"],
                    "angle": annotation["angle"],
                }
            elif annotation_type == "mask":
                annotation_meta = {"parts": annotation["parts"]}
            elif annotation_type == "template":
                annotation_meta = {
                    "connections": annotation["connections"],
                    "points": annotation["points"],
                }
            annotation_error = annotation.get("error")
            annotation_probability = annotation.get("probability")
            annotation_point_labels = annotation.get("pointLabels")
            attributes = annotation.get("attributes")
            user_metadata = __get_user_metadata(annotation)
            folder_name = None
            if annotation_path.parent != Path(project_root):
                folder_name = annotation_path.parent.name
            num_added = 0
            if not attributes:
                annotation_dict = {
                    "imageName": image_name,
                    "instanceId": annotation_instance_id,
                    "className": annotation_class_name,
                    "type": annotation_type,
                    "locked": annotation_locked,
                    "visible": annotation_visible,
                    "trackingId": annotation_tracking_id,
                    "meta": annotation_meta,
                    "error": annotation_error,
                    "probability": annotation_probability,
                    "pointLabels": annotation_point_labels,
                    "classColor": annotation_class_color,
                    "groupId": annotation_group_id,
                    "folderName": folder_name,
                }
                annotation_dict.update(user_metadata)
                annotation_dict.update(image_metadata)
                __append_annotation(annotation_dict)
                num_added = 1
            else:
                for attribute in attributes:
                    attribute_group = attribute.get("groupName")
                    attribute_name = attribute.get("name")
                    if (
                        attribute_group
                        not in class_group_name_to_values[annotation_class_name]
                    ):
                        logger.warning(
                            "Annotation class group %s not in classes json. Skipping.",
                            attribute_group,
                        )
                        continue
                    if (
                        attribute_name
                        not in class_group_name_to_values[annotation_class_name][
                            attribute_group
                        ]
                    ):
                        logger.warning(
                            "Annotation class group value %s not in classes json. Skipping.",
                            attribute_name,
                        )
                        continue
                    annotation_dict = {
                        "imageName": image_name,
                        "instanceId": annotation_instance_id,
                        "className": annotation_class_name,
                        "attributeGroupName": attribute_group,
                        "attributeName": attribute_name,
                        "type": annotation_type,
                        "locked": annotation_locked,
                        "visible": annotation_visible,
                        "trackingId": annotation_tracking_id,
                        "meta": annotation_meta,
                        "error": annotation_error,
                        "probability": annotation_probability,
                        "pointLabels": annotation_point_labels,
                        "classColor": annotation_class_color,
                        "groupId": annotation_group_id,
                        "folderName": folder_name,
                    }
                    annotation_dict.update(user_metadata)
                    annotation_dict.update(image_metadata)
                    __append_annotation(annotation_dict)
                    num_added += 1

            if num_added > 0:
                annotation_instance_id += 1

    df = pd.DataFrame(annotation_data)

    # Add classes/attributes w/o annotations
    if include_classes_wo_annotations:
        for class_meta in classes_json:
            annotation_class_name = class_meta["name"]
            annotation_class_color = class_meta["color"]

            if annotation_class_name not in df["className"].unique():
                __append_annotation(
                    {
                        "className": annotation_class_name,
                        "classColor": annotation_class_color,
                    }
                )
                continue

            class_df = df[df["className"] == annotation_class_name][
                ["className", "attributeGroupName", "attributeName"]
            ]
            attribute_groups = class_meta["attribute_groups"]

            for attribute_group in attribute_groups:

                attribute_group_name = attribute_group["name"]

                attribute_group_df = class_df[
                    class_df["attributeGroupName"] == attribute_group_name
                ][["attributeGroupName", "attributeName"]]
                attributes = attribute_group["attributes"]
                for attribute in attributes:
                    attribute_name = attribute["name"]

                    if not (
                        attribute_name in attribute_group_df["attributeName"].unique()
                    ):
                        __append_annotation(
                            {
                                "className": annotation_class_name,
                                "classColor": annotation_class_color,
                                "attributeGroupName": attribute_group_name,
                                "attributeName": attribute_name,
                            }
                        )

        df = pd.DataFrame(annotation_data)

    df = df.astype({"probability": float})

    return df


def instance_consensus(inst_1, inst_2):
    """Helper function that computes consensus score between two instances:

    :param inst_1: First instance for consensus score.
    :type inst_1: shapely object
    :param inst_2: Second instance for consensus score.
    :type inst_2: shapely object

    """
    if inst_1.type == inst_2.type == "Polygon":
        intersect = inst_1.intersection(inst_2)
        union = inst_1.union(inst_2)
        score = intersect.area / union.area
    elif inst_1.type == inst_2.type == "Point":
        score = -1 * inst_1.distance(inst_2)
    else:
        raise NotImplementedError

    return score


def image_consensus(df, image_name, annot_type):
    """Helper function that computes consensus score for instances of a single image:

    :param df: Annotation data of all images
    :type df: pandas.DataFrame
    :param image_name: The image name for which the consensus score will be computed
    :type image_name: str
    :param annot_type: Type of annotation instances to consider. Available candidates are: ["bbox", "polygon", "point"]
    :type dataset_format: str

    """

    try:
        from shapely.geometry import box
        from shapely.geometry import Point
        from shapely.geometry import Polygon
    except ImportError:
        raise ImportError(
            "To use superannotate.benchmark or superannotate.consensus functions please install "
            "shapely package in Anaconda enviornment with # conda install shapely"
        )

    image_df = df[df["imageName"] == image_name]
    all_projects = list(set(df["folderName"]))
    column_names = [
        "creatorEmail",
        "imageName",
        "instanceId",
        "area",
        "className",
        "attributes",
        "folderName",
        "score",
    ]
    instance_id = 0
    image_data = {}
    for column_name in column_names:
        image_data[column_name] = []

    projects_shaply_objs = {}
    # generate shapely objects of instances
    for _, row in image_df.iterrows():
        if row["folderName"] not in projects_shaply_objs:
            projects_shaply_objs[row["folderName"]] = []
        inst_data = row["meta"]
        if annot_type == "bbox":
            inst_coords = inst_data["points"]
            x1, x2 = inst_coords["x1"], inst_coords["x2"]
            y1, y2 = inst_coords["y1"], inst_coords["y2"]
            inst = box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        elif annot_type == "polygon":
            inst_coords = inst_data["points"]
            shapely_format = []
            for i in range(0, len(inst_coords) - 1, 2):
                shapely_format.append((inst_coords[i], inst_coords[i + 1]))
            inst = Polygon(shapely_format)
        elif annot_type == "point":
            inst = Point(inst_data["x"], inst_data["y"])
        if inst.is_valid:
            projects_shaply_objs[row["folderName"]].append(
                (inst, row["className"], row["creatorEmail"], row["attributes"])
            )
        else:
            logger.info(
                "Invalid %s instance occured, skipping to the next one.", annot_type
            )
    visited_instances = {}
    for proj, instances in projects_shaply_objs.items():
        visited_instances[proj] = [False] * len(instances)

    # match instances
    for curr_proj, curr_proj_instances in projects_shaply_objs.items():
        for curr_id, curr_inst_data in enumerate(curr_proj_instances):
            curr_inst, curr_class, _, _ = curr_inst_data
            if visited_instances[curr_proj][curr_id] == True:
                continue
            max_instances = []
            for other_proj, other_proj_instances in projects_shaply_objs.items():
                if curr_proj == other_proj:
                    max_instances.append((curr_proj, *curr_inst_data))
                    visited_instances[curr_proj][curr_id] = True
                else:
                    if annot_type in ["polygon", "bbox"]:
                        max_score = 0
                    else:
                        max_score = float("-inf")
                    max_inst_data = None
                    max_inst_id = -1
                    for other_id, other_inst_data in enumerate(other_proj_instances):
                        other_inst, other_class, _, _ = other_inst_data
                        if visited_instances[other_proj][other_id] == True:
                            continue
                        score = instance_consensus(curr_inst, other_inst)
                        if score > max_score and other_class == curr_class:
                            max_score = score
                            max_inst_data = other_inst_data
                            max_inst_id = other_id
                    if max_inst_data is not None:
                        max_instances.append((other_proj, *max_inst_data))
                        visited_instances[other_proj][max_inst_id] = True
            if len(max_instances) == 1:
                image_data["creatorEmail"].append(max_instances[0][3])
                image_data["attributes"].append(max_instances[0][4])
                image_data["area"].append(max_instances[0][1].area)
                image_data["imageName"].append(image_name)
                image_data["instanceId"].append(instance_id)
                image_data["className"].append(max_instances[0][2])
                image_data["folderName"].append(max_instances[0][0])
                image_data["score"].append(0)
            else:
                for curr_match_data in max_instances:
                    proj_cons = 0
                    for other_match_data in max_instances:
                        if curr_match_data[0] != other_match_data[0]:
                            score = instance_consensus(
                                curr_match_data[1], other_match_data[1]
                            )
                            proj_cons += 1.0 if score <= 0 else score
                    image_data["creatorEmail"].append(curr_match_data[3])
                    image_data["attributes"].append(curr_match_data[4])
                    image_data["area"].append(curr_match_data[1].area)
                    image_data["imageName"].append(image_name)
                    image_data["instanceId"].append(instance_id)
                    image_data["className"].append(curr_match_data[2])
                    image_data["folderName"].append(curr_match_data[0])
                    image_data["score"].append(proj_cons / (len(all_projects) - 1))
            instance_id += 1

    return image_data


def consensus_plot(consensus_df, *_, **__):
    plot_data = consensus_df.copy()

    # annotator-wise boxplot
    annot_box_fig = px.box(
        plot_data,
        x="creatorEmail",
        y="score",
        points="all",
        color="creatorEmail",
        color_discrete_sequence=px.colors.qualitative.Dark24,
    )
    annot_box_fig.show()

    # project-wise boxplot
    project_box_fig = px.box(
        plot_data,
        x="folderName",
        y="score",
        points="all",
        color="folderName",
        color_discrete_sequence=px.colors.qualitative.Dark24,
    )
    project_box_fig.show()

    # scatter plot of score vs area
    fig = px.scatter(
        plot_data,
        x="area",
        y="score",
        color="className",
        symbol="creatorEmail",
        facet_col="folderName",
        color_discrete_sequence=px.colors.qualitative.Dark24,
        hover_data={
            "className": False,
            "imageName": True,
            "folderName": False,
            "area": False,
            "score": False,
        },
    )
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.for_each_trace(lambda t: t.update(name=t.name.split("=")[-1]))
    fig.show()
