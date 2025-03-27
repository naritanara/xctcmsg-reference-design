`include "xctcmsg_defs.svh"

module commit_safety_unit (
  // Post office
  input  commit_safety_request_t postoffice_csu_request,
  output logic csu_postoffice_grant,

  // Mailbox
  input  commit_safety_request_t mailbox_csu_request,
  output logic csu_mailbox_grant
);

always_comb begin : no_check_stub
  csu_postoffice_grant = 1;
  csu_mailbox_grant = 1;
end

endmodule
