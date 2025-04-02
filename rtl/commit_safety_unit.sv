import xctcmsg_pkg::*;

module commit_safety_unit (
  // Post office
  input  commit_safety_request_t postoffice_csu_request,
  output logic csu_postoffice_grant,

  // Mailbox
  input  commit_safety_request_t mailbox_csu_request,
  output logic csu_mailbox_grant,

  // Control unit
  input  commit_safety_control_unit_state_t control_unit_csu_state
);

`ifdef XCTCMSG_SARGANTANA
always_comb begin : is_next_in_graduation_list
  csu_postoffice_grant = postoffice_csu_request.payload == control_unit_csu_state;
  csu_mailbox_grant = mailbox_csu_request.payload == control_unit_csu_state;
end
`else
always_comb begin : no_check_stub
  csu_postoffice_grant = 1;
  csu_mailbox_grant = 1;
end
`endif

endmodule
