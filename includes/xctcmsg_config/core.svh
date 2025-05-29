`ifndef XCTCMSG_CONFIG__CORE_SVH
`define XCTCMSG_CONFIG__CORE_SVH

// Core configuration -> Parameters corresponding to the core that contains the
//                       functional unit.
`ifdef XCTCMSG_CORE_SARGANTANA
  import drac_pkg::*;

  parameter type exe_stage_passthrough_t = drac_pkg::rr_exe_arith_instr_t;
  parameter type commit_safety_request_payload_t = drac_pkg::gl_index_t;
  parameter type commit_safety_control_unit_state_t = drac_pkg::gl_index_t;
`elsif XCTCMSG_CORE_UNIT_TEST
  typedef struct packed {
    logic [4:0] rd;
  } unit_test_exe_stage_passthrough_t;

  parameter type exe_stage_passthrough_t = unit_test_exe_stage_passthrough_t;
  parameter type commit_safety_request_payload_t = logic;
  parameter type commit_safety_control_unit_state_t = logic;
`else
  `error "Missing or unrecognized `XCTCMSG_CORE_* define"
`endif

`endif // XCTCMSG_CONFIG__CORE_SVH
