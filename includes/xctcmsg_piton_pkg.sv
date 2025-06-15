package xctcmsg_piton_pkg;

import xctcmsg_pkg::*;

`ifdef PITON_RV64_XCTCMSG
  `include "define.tmp.h"
`else
  // From openpiton's "define.tmp.h" and "network_define.v", for unit tests
  `define NOC_X_WIDTH 8
  `define NOC_Y_WIDTH 8

  `define MSG_LENGTH_WIDTH 8
  `define MSG_DST_FBITS_WIDTH 4
  `define MSG_DST_Y_WIDTH `NOC_Y_WIDTH
  `define MSG_DST_X_WIDTH `NOC_X_WIDTH
  `define MSG_DST_CHIPID_WIDTH 14

  `define PITON_XCTCMSG_NOC_WIDTH 192

  `define XCTCMSG_MSG_HEADER_WIDTH 64
  `define XCTCMSG_MSG_RESERVED 21:0

  `define XCTCMSG_MSG_PAYLOAD_WIDTH 128
  `define XCTCMSG_MSG_PAYLOAD_LENGTH (`XCTCMSG_MSG_PAYLOAD_WIDTH / 64)

  // This defines should only be used when the openpiton network is not in use
  `ifndef PITON_X_TILES
    `define PITON_X_TILES 1
  `endif
  `ifndef PITON_Y_TILES
    `define PITON_Y_TILES 1
  `endif
`endif

`define XCTCMSG_MSG_RESERVED_WIDTH $size(logic[`XCTCMSG_MSG_RESERVED])

parameter OPENPITON_X_TILES = `PITON_X_TILES;
parameter OPENPITON_Y_TILES = `PITON_Y_TILES;

parameter NOC_MSG_PAYLOAD_LENGTH = `XCTCMSG_MSG_PAYLOAD_LENGTH;

parameter NOC_MSG_DST_CHIPID_WIDTH = `MSG_DST_CHIPID_WIDTH;
typedef logic[NOC_MSG_DST_CHIPID_WIDTH-1:0] openpiton_msg_dst_chipid_t;
parameter NOC_MSG_DST_X_WIDTH = `MSG_DST_X_WIDTH;
typedef logic[NOC_MSG_DST_X_WIDTH-1:0] openpiton_msg_dst_x_t;
parameter NOC_MSG_DST_Y_WIDTH = `MSG_DST_Y_WIDTH;
typedef logic[NOC_MSG_DST_Y_WIDTH-1:0] openpiton_msg_dst_y_t;
parameter NOC_MSG_DST_FBITS_WIDTH = `MSG_DST_FBITS_WIDTH;
typedef logic[NOC_MSG_DST_FBITS_WIDTH-1:0] openpiton_msg_dst_fbits_t;
parameter NOC_MSG_LENGTH_WIDTH = `MSG_LENGTH_WIDTH;
typedef logic[NOC_MSG_LENGTH_WIDTH-1:0] openpiton_msg_length_t;
parameter NOC_MSG_RESERVED_WIDTH = `XCTCMSG_MSG_RESERVED_WIDTH;
typedef logic[NOC_MSG_RESERVED_WIDTH-1:0] openpiton_msg_reserved_t;

typedef struct packed {
  openpiton_msg_dst_chipid_t dst_chipid;
  openpiton_msg_dst_x_t dst_x;
  openpiton_msg_dst_y_t dst_y;
  openpiton_msg_dst_fbits_t dst_fbits;
  openpiton_msg_length_t length;
  openpiton_msg_reserved_t reserved;
} openpiton_noc_header_parts_t;

parameter NOC_HEADER_WIDTH = `XCTCMSG_MSG_HEADER_WIDTH;
typedef logic[NOC_HEADER_WIDTH-1:0] openpiton_raw_noc_header_t;

typedef union packed {
  openpiton_noc_header_parts_t parts;
  openpiton_raw_noc_header_t raw;
} openpiton_noc_header_t;

typedef struct packed {
  xctcmsg_pkg::message_data_t data;
  xctcmsg_pkg::message_tag_t tag;
  xctcmsg_pkg::message_addr_t source;
} openpiton_noc_payload_parts_t;

parameter NOC_PAYLOAD_WIDTH = `XCTCMSG_MSG_PAYLOAD_WIDTH;
typedef logic[NOC_PAYLOAD_WIDTH-1:0] openpiton_raw_noc_payload_t;

typedef union packed {
  openpiton_noc_payload_parts_t parts;
  openpiton_raw_noc_payload_t raw;
} openpiton_noc_payload_t;

typedef struct packed {
  openpiton_noc_payload_t payload;
  openpiton_noc_header_t header;
} openpiton_noc_parts_t;

parameter NOC_WIDTH = `PITON_XCTCMSG_NOC_WIDTH;
typedef logic[NOC_WIDTH-1:0] openpiton_raw_noc_t;

typedef union packed {
  openpiton_noc_parts_t parts;
  openpiton_raw_noc_t raw;
} openpiton_noc_t;

endpackage
