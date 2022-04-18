"""
Constants for working with video files.

Notes:
    - 8-bit formats: ``ffmpeg -pix_fmts | grep '^[I.]O' | grep '8-8' | awk '{print $2}' | sort``
    - 10-bit formats: ``ffmpeg -pix_fmts | grep '^[I.]O' | grep '10-10' | awk '{print $2}' | sort``

:author: Doug Skrypa
"""
# fmt: off

FFMPEG_CONFIG_PATH = '~/.config/ds_tools/ffmpeg.json'

NAME_RESOLUTION_MAP = {'720p': (1280, 720), '1080p': (1920, 1080), '1440p': (2560, 1440), '2160p': (3840, 2160)}

CODEC_DEFAULT_EXT_MAP = {'av1': 'mkv', 'vp9': 'mkv', 'h265': 'mkv', 'h264': 'mp4'}

ENCODER_CODEC_MAP = {
    'libsvtav1': 'av1', 'libaom-av1': 'av1',
    'libvpx-vp9': 'vp9',
    # 'libx265': 'h265', 'hevc_nvenc': 'h265',
    # 'libx264': 'h264', 'h264_nvenc': 'h264',
}

ENCODER_PIXEL_FORMATS = {
    'libsvtav1': {'yuv420p', 'yuv420p10le'},
    'libaom-av1': {
        'yuv420p', 'yuv422p', 'yuv444p', 'gbrp', 'yuv420p10le', 'yuv422p10le', 'yuv444p10le', 'yuv420p12le',
        'yuv422p12le', 'yuv444p12le', 'gbrp10le', 'gbrp12le', 'gray', 'gray10le', 'gray12le',
    },
    'libvpx-vp9': {
        'yuv420p', 'yuva420p', 'yuv422p', 'yuv440p', 'yuv444p', 'yuv420p10le', 'yuv422p10le', 'yuv440p10le',
        'yuv444p10le', 'yuv420p12le', 'yuv422p12le', 'yuv440p12le', 'yuv444p12le', 'gbrp', 'gbrp10le', 'gbrp12le',
    },
    'libx265': {
        'yuv420p', 'yuvj420p', 'yuv422p', 'yuvj422p', 'yuv444p', 'yuvj444p', 'gbrp', 'yuv420p10le', 'yuv422p10le',
        'yuv444p10le', 'gbrp10le', 'yuv420p12le', 'yuv422p12le', 'yuv444p12le', 'gbrp12le', 'gray', 'gray10le',
        'gray12le',
    },
    'hevc_nvenc': {
        'yuv420p', 'nv12', 'p010le', 'yuv444p', 'p016le', 'yuv444p16le', 'bgr0', 'rgb0', 'gbrp', 'gbrp16le', 'cuda',
        'd3d11',
    },
    'libx264': {
        'yuv420p', 'yuvj420p', 'yuv422p', 'yuvj422p', 'yuv444p', 'yuvj444p', 'nv12', 'nv16', 'nv21', 'yuv420p10le',
        'yuv422p10le', 'yuv444p10le', 'nv20le', 'gray', 'gray10le',
    },
    'h264_nvenc': {
        'yuv420p', 'nv12', 'p010le', 'yuv444p', 'p016le', 'yuv444p16le', 'bgr0', 'rgb0', 'gbrp', 'gbrp16le', 'cuda',
        'd3d11',
    },
}

# Additional info: https://trac.ffmpeg.org/wiki/Chroma%20Subsampling
PIXEL_FORMATS_8_BIT = {
    '0bgr', '0rgb', 'abgr', 'argb', 'bgr0', 'bgr24', 'bgra', 'gbrap', 'gbrp', 'nv12', 'nv21', 'nv24', 'nv42', 'rgb0',
    'rgb24', 'rgba', 'uyvy422', 'ya8', 'yuv410p', 'yuv411p', 'yuv420p', 'yuv422p', 'yuv440p', 'yuv444p', 'yuva420p',
    'yuva422p', 'yuva444p', 'yuvj411p', 'yuvj420p', 'yuvj422p', 'yuvj440p', 'yuvj444p', 'yuyv422', 'yvyu422',
}
PIXEL_FORMATS_10_BIT = {
    'gbrap10be', 'gbrap10le', 'gbrp10be', 'gbrp10le', 'p010be', 'p010le', 'p210be', 'p210le', 'p410be', 'p410le',
    'x2bgr10le', 'x2rgb10le', 'yuv420p10be', 'yuv420p10le', 'yuv422p10be', 'yuv422p10le', 'yuv440p10be', 'yuv440p10le',
    'yuv444p10be', 'yuv444p10le', 'yuva420p10be', 'yuva420p10le', 'yuva422p10be', 'yuva422p10le', 'yuva444p10be',
    'yuva444p10le',
}
