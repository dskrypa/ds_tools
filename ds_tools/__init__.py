
import logging
# import os
# import sys

# ds_tools_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if ds_tools_path not in sys.path:
#     sys.path.append(ds_tools_path)

logging.getLogger("ds_tools").addHandler(logging.NullHandler())
logging.root.addHandler(logging.NullHandler())
