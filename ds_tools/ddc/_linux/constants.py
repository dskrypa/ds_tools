from __future__ import annotations

from enum import IntEnum


# fmt: off
I2C_RDWR = 0x0707   # ioctl definition
MAGIC_1 = 0x51      # = 81      first byte to send, host address
MAGIC_2 = 0x80      # = 128     second byte to send, or'd with length
MAGIC_XOR = 0x50    # = 80      initial xor for received frame
EDID_ADDR = 0x50    # = 80
DDCCI_ADDR = 0x37   # = 55
DDCCI_CHECK = 0x6E  # = 110 = DDCCI_ADDR << 1
# fmt: on

# DELAY = 0.2
DELAY = 0.05


class DDCPacketType(IntEnum):
    # fmt: off
    NONE = 0x0
    QUERY_VCP_REQUEST = 0x01
    QUERY_VCP_RESPONSE = 0x02
    SET_VCP_REQUEST = 0x03          # n. no reply message
    SAVE_CURRENT_SETTINGS = 0x0C    # n. no reply message
    CAPABILITIES_REQUEST = 0xF3
    CAPABILITIES_RESPONSE = 0xE3
    ID_REQUEST = 0xF1
    ID_RESPONSE = 0xE1
    TABLE_READ_REQUEST = 0xE2
    TABLE_READ_RESPONSE = 0xE4
    TABLE_WRITE_REQUEST = 0xE7
    # fmt: on
