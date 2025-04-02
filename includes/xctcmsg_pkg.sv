package xctcmsg_pkg;

`ifdef XCTCMSG_SARGANTANA
import drac_pkg::rr_exe_arith_instr_t;
import drac_pkg::gl_index_t;
typedef rr_exe_arith_instr_t exe_stage_passthrough_t;
typedef gl_index_t commit_safety_request_payload_t;
typedef gl_index_t commit_safety_control_unit_state_t;
`else
typedef logic exe_stage_passthrough_t;
typedef logic commit_safety_request_payload_t;
typedef logic commit_safety_control_unit_state_t;
`endif

typedef struct packed {
  logic [2:0] funct3;
  logic [63:0] rs1;
  logic [63:0] rs2;
  logic [4:0] rd;
  exe_stage_passthrough_t passthrough;
} request_data_t;

typedef enum logic [2:0] {
  REQUEST_TYPE_SEND  = 3'b000,
  REQUEST_TYPE_RECV  = 3'b001,
  REQUEST_TYPE_AVAIL = 3'b010
} request_type_t;

`define MESSAGE_ADDR_WIDTH 32
`define MESSAGE_ADDR_MASK  (`MESSAGE_ADDR_WIDTH-1):0
typedef logic [`MESSAGE_ADDR_MASK] message_addr_t;

`define MESSAGE_TAG_WIDTH 32
`define MESSAGE_TAG_MASK  (`MESSAGE_TAG_WIDTH-1):0
typedef logic [`MESSAGE_TAG_MASK] message_tag_t;

`define MESSAGE_DATA_WIDTH 64
`define MESSAGE_DATA_MASK  (`MESSAGE_DATA_WIDTH-1):0
typedef logic [`MESSAGE_DATA_MASK] message_data_t;

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
  logic [4:0] register;
  exe_stage_passthrough_t passthrough;
} send_queue_data_t;

typedef struct packed {
  logic is_avail;
  message_metadata_t meta;
  message_metadata_t meta_mask;
  logic [4:0] register;
  exe_stage_passthrough_t passthrough;
} receive_queue_data_t;

typedef struct packed {
  logic [4:0] register;
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
