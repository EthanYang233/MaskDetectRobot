import numpy as np
import cv2
from timeit import default_timer as timer
import math
import tensorflow as tf
if tf.__version__ > '2':
    import tensorflow.compat.v1 as tf  

class Args():
    def __init__(self):
        self.device = 'cpu'
        self.model_path = '/home/pi/Desktop/face_mask_detection.pb'
        self.feature_map_sizes = [[33, 33], [17, 17], [9, 9], [5, 5], [3, 3]]
        self.anchor_sizes = [[0.04, 0.056], [0.08, 0.11], [0.16, 0.22], [0.32, 0.45], [0.64, 0.72]]
        self.anchor_ratios = [[1, 0.62, 0.42]] * 5
        self.img_path = '/home/pi/Desktop/test2.jpg'    

args = Args()

def decode_bbox(anchors, raw_outputs, variances=[0.1, 0.1, 0.2, 0.2]):
    
    anchor_centers_x = (anchors[:, :, 0:1] + anchors[:, :, 2:3]) / 2
    anchor_centers_y = (anchors[:, :, 1:2] + anchors[:, :, 3:]) / 2
    anchors_w = anchors[:, :, 2:3] - anchors[:, :, 0:1]
    anchors_h = anchors[:, :, 3:] - anchors[:, :, 1:2]
    raw_outputs_rescale = raw_outputs * np.array(variances)
    predict_center_x = raw_outputs_rescale[:, :, 0:1] * anchors_w + anchor_centers_x
    predict_center_y = raw_outputs_rescale[:, :, 1:2] * anchors_h + anchor_centers_y
    predict_w = np.exp(raw_outputs_rescale[:, :, 2:3]) * anchors_w
    predict_h = np.exp(raw_outputs_rescale[:, :, 3:]) * anchors_h
    predict_xmin = predict_center_x - predict_w / 2
    predict_ymin = predict_center_y - predict_h / 2
    predict_xmax = predict_center_x + predict_w / 2
    predict_ymax = predict_center_y + predict_h / 2
    predict_bbox = np.concatenate([predict_xmin, predict_ymin, predict_xmax, predict_ymax], axis=-1)
    return predict_bbox

def generate_anchors(feature_map_sizes, anchor_sizes, anchor_ratios, offset=0.5):

    anchor_bboxes = []
    for idx, feature_size in enumerate(feature_map_sizes):
        cx = (np.linspace(0, feature_size[0] - 1, feature_size[0]) + 0.5) / feature_size[0]
        cy = (np.linspace(0, feature_size[1] - 1, feature_size[1]) + 0.5) / feature_size[1]
        cx_grid, cy_grid = np.meshgrid(cx, cy)
        cx_grid_expend = np.expand_dims(cx_grid, axis=-1)
        cy_grid_expend = np.expand_dims(cy_grid, axis=-1)
        center = np.concatenate((cx_grid_expend, cy_grid_expend), axis=-1)

        num_anchors = len(anchor_sizes[idx]) +  len(anchor_ratios[idx]) - 1
        center_tiled = np.tile(center, (1, 1, 2* num_anchors))
        anchor_width_heights = []

        # different scales with the first aspect ratio
        for scale in anchor_sizes[idx]:
            ratio = anchor_ratios[idx][0] # select the first ratio
            width = scale * np.sqrt(ratio)
            height = scale / np.sqrt(ratio)
            anchor_width_heights.extend([-width / 2.0, -height / 2.0, width / 2.0, height / 2.0])

        # the first scale, with different aspect ratios (except the first one)
        for ratio in anchor_ratios[idx][1:]:
            s1 = anchor_sizes[idx][0] # select the first scale
            width = s1 * np.sqrt(ratio)
            height = s1 / np.sqrt(ratio)
            anchor_width_heights.extend([-width / 2.0, -height / 2.0, width / 2.0, height / 2.0])

        bbox_coords = center_tiled + np.array(anchor_width_heights)
        bbox_coords_reshape = bbox_coords.reshape((-1, 4))
        anchor_bboxes.append(bbox_coords_reshape)
    anchor_bboxes = np.expand_dims(np.concatenate(anchor_bboxes, axis=0), axis=0)
    return anchor_bboxes


def single_class_non_max_suppression(bboxes, confidences, conf_thresh=0.7, iou_thresh=0.5, keep_top_k=-1):

    if len(bboxes) == 0: return []

    conf_keep_idx = np.where(confidences > conf_thresh)[0]

    bboxes = bboxes[conf_keep_idx]
    confidences = confidences[conf_keep_idx]

    pick = []
    xmin = bboxes[:, 0]
    ymin = bboxes[:, 1]
    xmax = bboxes[:, 2]
    ymax = bboxes[:, 3]

    area = (xmax - xmin + 1e-3) * (ymax - ymin + 1e-3)
    idxs = np.argsort(confidences)

    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)

        # keep top k
        if keep_top_k != -1:
            if len(pick) >= keep_top_k:
                break

        overlap_xmin = np.maximum(xmin[i], xmin[idxs[:last]])
        overlap_ymin = np.maximum(ymin[i], ymin[idxs[:last]])
        overlap_xmax = np.minimum(xmax[i], xmax[idxs[:last]])
        overlap_ymax = np.minimum(ymax[i], ymax[idxs[:last]])
        overlap_w = np.maximum(0, overlap_xmax - overlap_xmin)
        overlap_h = np.maximum(0, overlap_ymax - overlap_ymin)
        overlap_area = overlap_w * overlap_h
        overlap_ratio = overlap_area / (area[idxs[:last]] + area[i] - overlap_area)

        need_to_be_deleted_idx = np.concatenate(([last], np.where(overlap_ratio > iou_thresh)[0]))
        idxs = np.delete(idxs, need_to_be_deleted_idx)

    return conf_keep_idx[pick]

def test(image,
        conf_thresh=0.5,
        iou_thresh=0.4,
        target_shape=(160, 160),
        anchors=None,
        ):

    output_info = []
    id2class = {0: 'Mask', 1: 'NoMask'}
    height, width, _ = image.shape
    image = cv2.resize(image, target_shape) / 255.0
    image_exp = np.expand_dims(image, axis=0) #batch_size = 1

    
    image_tensor = graph.get_tensor_by_name('data_1:0')
    detection_bboxes = graph.get_tensor_by_name('loc_branch_concat_1/concat:0')
    detection_scores = graph.get_tensor_by_name('cls_branch_concat_1/concat:0')
    
    y_bboxes_output, y_cls_output = sess.run([detection_bboxes, detection_scores],
                            feed_dict={image_tensor: image_exp})
    #anchors_exp = np.expand_dims(anchors, axis=0)
    y_bboxes = decode_bbox(anchors, y_bboxes_output)[0]
    y_cls = y_cls_output[0]
    # To speed up, do single class NMS, not multiple classes NMS.
    bbox_max_scores = np.max(y_cls, axis=1)
    bbox_max_score_classes = np.argmax(y_cls, axis=1)

    # keep_idx is the alive bounding box after nms.
    keep_idxs = single_class_non_max_suppression(y_bboxes,
                                                 bbox_max_scores,
                                                 conf_thresh=conf_thresh,
                                                 iou_thresh=iou_thresh,
                                                 )

    for idx in keep_idxs:
        conf = float(bbox_max_scores[idx])
        class_id = bbox_max_score_classes[idx]
        bbox = y_bboxes[idx]
        # clip the coordinate, avoid the value exceed the image boundary.
        xmin = max(0, int(bbox[0] * width))
        ymin = max(0, int(bbox[1] * height))
        xmax = min(int(bbox[2] * width), width)
        ymax = min(int(bbox[3] * height), height)

        if class_id == 0:
            color = (0, 255, 0)
        else:
            color = (255, 0, 0)
        cv2.rectangle(image, (xmin, ymin), (xmax, ymax), color, 2)
        cv2.putText(image, "%s: %.2f" % (id2class[class_id], conf), (xmin + 2, ymin - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color)


        output_info.append([class_id, conf, xmin, ymin, xmax, ymax])
    
    return output_info

def model_load(model_path):
    detection_graph = tf.Graph()
    with detection_graph.as_default():
        od_graph_def = tf.GraphDef()
        with tf.gfile.GFile(model_path, 'rb') as fid:
            serialized_graph = fid.read()
            od_graph_def.ParseFromString(serialized_graph)
            tf.import_graph_def(od_graph_def, name='')
            with detection_graph.as_default():
                sess = tf.Session(graph=detection_graph)
                return sess, detection_graph



class Detector():
    def __init__(self, model_dir, img_dir):
        self.model_dir = model_dir
        self.img_dir = img_dir
        self.model = model_load(self.model_dir)
        self.anchors = generate_anchors(args.feature_map_sizes, args.anchor_sizes, args.anchor_ratios)
    
    def checkMask(self):
        tic = timer()
        img = cv2.imread(self.img_dir)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ans = test(img, target_shape=(260, 260), anchors=self.anchors)
        toc = timer()
        print(toc - tic)
        print(ans)
        return ans

sess, graph = model_load(args.model_path)
anchors = generate_anchors(args.feature_map_sizes, args.anchor_sizes, args.anchor_ratios)


#if __name__ == "main":       
detec = Detector(args.model_path, args.img_path)
#while(1):
#tic = timer()
while(1):
    detec.checkMask()
#toc = timer()
#print(toc - tic)

"""import multiprocessing
pool = multiprocessing.Pool(processes = 2)
tic = timer()
#while(1):
img = cv2.imread(args.img_path)
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
pool.apply_async(test,(img, True, (360, 360), anchors, model))
pool.close()
pool.join()
#pool.apply_async(test,(img, True, (360, 360), anchors, model))
#test(img, show_result=True, target_shape=(360, 360), anchors=anchors, model=model)
toc = timer()
print(toc - tic)"""





