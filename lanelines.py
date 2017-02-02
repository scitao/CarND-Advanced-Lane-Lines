from itertools import groupby, islice, zip_longest, cycle, filterfalse
from matplotlib.widgets import Button
import cv2
import glob
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import util


plt.ion()


# Camera Calibration

def measure_distortion(calibration_files):
    files = calibration_files
    objp = np.zeros((9*6,3), np.float32)
    objp[:,:2] = np.mgrid[0:9,0:6].T.reshape(-1,2)
    stage1 = map(lambda x: (x,), cycle(files))
    stage2 = map(lambda x: x + (mpimg.imread(x[0]),), stage1)
    stage3 = map(lambda x: x + (cv2.findChessboardCorners(cv2.cvtColor(x[1], cv2.COLOR_RGB2GRAY), (9,6)),), stage2)
    stage4 = map(lambda x: x + (cv2.drawChessboardCorners(np.copy(x[1]), (9,6), *(x[2][::-1])),), stage3)
    filenames,images,corners,annotated_images = zip(*filter(lambda x: x[2][0], islice(stage4, len(files))))
    _,imgpoints = zip(*corners)
    objpoints = [objp for i in range(len(imgpoints))]
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, list(islice(stage2,1))[0][1].shape[:2:][::-1], None, None)
    return mtx, dist, annotated_images


# Distortion Correction

def get_undistorter(calibration_files):
    mtx,dist,annotated_images = measure_distortion(calibration_files)
    return lambda x: cv2.undistort(x, mtx, dist, None, mtx), annotated_images


undistort,_ = get_undistorter(glob.glob("camera_cal/*.jpg"))


# Perspective Transform

def measure_warp(corrected_image):
    def handler(e):
        if len(src)<1:
            plt.axvline(int(e.xdata), linewidth=2, color='r')
        if len(src)<4:
            src.append((int(e.xdata),int(e.ydata)))
        if len(src)<3:
            plt.axhline(int(e.ydata), linewidth=2, color='r')
        if len(src)==4:
            plt.axvline(int(e.xdata), linewidth=2, color='r')
            dst.extend([src[0], (src[0][0],src[1][1]), (src[3][0],src[2][1]), src[3]])
        else:
            pass
    plt.ion()
    fig = plt.figure()
    plt.imshow(corrected_image)
    global src
    global dst
    src = []
    dst = []
    cid1 = fig.canvas.mpl_connect('button_press_event', handler)
    cid2 = fig.canvas.mpl_connect('close_event', lambda e: e.canvas.stop_event_loop())
    fig.canvas.start_event_loop(timeout=-1)
    M = cv2.getPerspectiveTransform(np.asfarray(src, np.float32), np.asfarray(dst, np.float32))
    Minv = cv2.getPerspectiveTransform(np.asfarray(dst, np.float32), np.asfarray(src, np.float32))
    return M, Minv


def get_unwarper(corrected_image):
    M, Minv = measure_warp(corrected_image)
    return lambda x: cv2.warpPerspective(x, M, x.shape[:2][::-1], flags=cv2.INTER_LINEAR), M, Minv


unwarp,_,_ = get_unwarper(undistort(mpimg.imread("test_images/straight_lines1.jpg")))


# Gradient and Color thresholds


def scale(img, factor=255.0):
    scale_factor = np.max(img)/factor
    return (img/scale_factor).astype(np.uint8)


def derivative(img, sobel_kernel=3):
    derivx = np.absolute(cv2.Sobel(img, cv2.CV_64F, 1, 0, ksize=sobel_kernel))
    derivy = np.absolute(cv2.Sobel(img, cv2.CV_64F, 0, 1, ksize=sobel_kernel))
    gradmag = np.sqrt(derivx**2 + derivy**2)
    absgraddir = np.arctan2(derivy, derivx)
    return scale(derivx), scale(derivy), scale(gradmag), absgraddir


def grad(img, k1=3, k2=15):
    _,_,g,_ = derivative(img, sobel_kernel=k1)
    _,_,_,p = derivative(img, sobel_kernel=k2)
    return g,p


def hls_select(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HLS).astype(np.float)
    h = hsv[:,:,0]
    l = hsv[:,:,1]
    s = hsv[:,:,2]
    return h,l,s


def rgb_select(img):
    rgb = img
    r = rgb[:,:,0]
    g = rgb[:,:,1]
    b = rgb[:,:,2]
    return r,g,b
    

def threshold(img, thresh_min=0, thresh_max=255):
    binary_output = np.zeros_like(img)
    binary_output[(img >= thresh_min) & (img <= thresh_max)] = 1
    return binary_output


################################################################################

import builtins
builtins.theta = {
    'horizon':0.60,
    'hood':0.07,
    'trapezoid_top_factor':0.10,
    'trapezoid_bottom_factor':0.90,
    'angle_cutoff':0.75,
    'kernel_size':5,
    'low_threshold':50,
    'high_threshold':150,
    'rho':2,
    'theta':1,
    'threshold':30,
    'min_line_length':3,
    'max_line_gap':1}


def mask_image(img, vertices):
    return region_of_interest(img, vertices)


def process(img):
    img = np.copy(img)
    img = undistort(img)
    h,l,s = hls_select(img)
    r,g,b = rgb_select(img)
    g = util.blur_image(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY))
    grad_g = grad(util.blur_image(g),k1=3,k2=15)
    grad_r = grad(util.blur_image(r),k1=3,k2=15)
    grad_s = grad(util.blur_image(s),k1=3,k2=15)
    o0 = threshold(g, 180, 255)
    o1 = threshold(r, 200, 255)
    o2 = threshold(s, 90, 255)
    o3 = sand(threshold(grad_g[0], 40, 255), threshold(grad_g[1], 0.7, 1.3))
    o4 = sand(threshold(grad_r[0], 40, 255), threshold(grad_r[1], 0.7, 1.3))
    o5 = sand(threshold(grad_s[0], 40, 255), threshold(grad_s[1], 0.7, 1.3))
    o6 = sor(o1,o3,o4,o5)
    o7 = util.mask_image(scale(o6), util.trapezoid(img)[:,:,::-1])
    o8 = scale(unwarp(o7), factor=1)
    return o8



sand = lambda *x: np.logical_and.reduce(x)
sor = lambda *x: np.logical_or.reduce(x)

a = (process(mpimg.imread(f)) for f in cycle(glob.glob("test_images/*.jpg")))

# plt.imshow(np.dstack((np.zeros_like(corrected_image)[:,:,0], pipeline1(corrected_image), pipeline2(corrected_image))))

# plt.imshow(np.dstack((np.zeros_like(corrected_image)[:,:,0], pipeline1(corrected_image), pipeline2(corrected_image))),


# result = pipeline(corrected_image)
# f, (ax1, ax2) = plt.subplots(1, 2, figsize=(24, 9))
# f.tight_layout()
# ax1.imshow(corrected_image)
# ax1.set_title('Original Image', fontsize=40)
# ax2.imshow(result)
# ax2.set_title('Pipeline Result', fontsize=40)
# plt.subplots_adjust(left=0., right=1, top=0.9, bottom=0.)

calibration_image = undistort(mpimg.imread("test_images/straight_lines1.jpg"))
flat_image = unwarp(calibration_image)
fig = plt.figure()
plt.imshow(flat_image)
plt.savefig("fig3.png", format="png")
plt.close()
