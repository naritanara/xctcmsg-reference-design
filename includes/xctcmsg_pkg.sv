package xctcmsg_pkg;

`include "xctcmsg_config/core.svh"

typedef struct packed {
  logic [2:0] funct3;
  logic [63:0] rs1;
  logic [63:0] rs2;
  exe_stage_passthrough_t passthrough;
} request_data_t;

typedef enum logic [2:0] {
  REQUEST_TYPE_SEND  = 3'b000,
  REQUEST_TYPE_RECV  = 3'b001,
  REQUEST_TYPE_AVAIL = 3'b010
} request_type_t;

parameter MESSAGE_ADDR_WIDTH = 32;
typedef logic [MESSAGE_ADDR_WIDTH-1:0] message_addr_t;

parameter MESSAGE_TAG_WIDTH = 32;
typedef logic [MESSAGE_TAG_WIDTH-1:0] message_tag_t;

parameter MESSAGE_DATA_WIDTH = 64;
typedef logic [MESSAGE_DATA_WIDTH-1:0] message_data_t;

typedef struct packed {
  message_tag_t tag;
  message_addr_t address;
} message_metadata_t;

typedef struct packed {
  message_metadata_t meta;
  message_data_t data;
} message_t;

typedef struct packed {
  message_t message;
  exe_stage_passthrough_t passthrough;
} send_queue_data_t;

typedef struct packed {
  logic is_avail;
  message_metadata_t meta;
  message_metadata_t meta_mask;
  exe_stage_passthrough_t passthrough;
} receive_queue_data_t;

typedef struct packed {
  logic [63:0] value;
  exe_stage_passthrough_t passthrough;
} writeback_arbiter_data_t;

typedef struct packed {
  message_t message;
} interface_send_data_t;

typedef struct packed {
  message_t message;
} interface_receive_data_t;

typedef struct packed {
  commit_safety_request_payload_t payload;
} commit_safety_request_t;

endpackage
