package xctcmsg_cfg_pkg;

// Core configuration -> Parameters corresponding to the core that contains the
//                       functional unit.
`ifdef XCTCMSG_CORE_SARGANTANA
  class xctcmsg_core_cfg;
    import drac_pkg::*;
  
    parameter type exe_stage_passthrough_t = drac_pkg::rr_exe_arith_instr_t;
    parameter type commit_safety_request_payload_t = drac_pkg::gl_index_t;
    parameter type commit_safety_control_unit_state_t = drac_pkg::gl_index_t;
  endclass
`elsif XCTCMSG_CORE_UNIT_TEST
  typedef struct packed {
    logic [4:0] rd;
  } unit_test_exe_stage_passthrough_t;
  
  class xctcmsg_core_cfg;
    parameter type exe_stage_passthrough_t = unit_test_exe_stage_passthrough_t;
    parameter type commit_safety_request_payload_t = logic;
    parameter type commit_safety_control_unit_state_t = logic;
  endclass
`else
  `error "Missing or unrecognized `XCTCMSG_CORE_* define"
`endif

typedef enum {
  network_bus,
  network_openpiton
} network_t;

`ifdef XCTCMSG_NETWORK_BUS
  class xctcmsg_network_cfg;
    parameter network_t NETWORK = network_bus;
  endclass
`elsif XCTCMSG_NETWORK_OPENPITON
  class xctcmsg_network_cfg;
    parameter network_t NETWORK = network_openpiton;
  endclass
`else
  `error "Missing or unrecognized `XCTCMSG_NETWORK_* define"
`endif

endpackage