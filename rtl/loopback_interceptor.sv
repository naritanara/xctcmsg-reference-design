import xctcmsg_pkg::*;

module loopback_interceptor (
  input  message_addr_t local_address,

  // Post office
  input  logic postoffice_loopback_valid,
  output logic loopback_postoffice_ready,
  input  interface_send_data_t postoffice_loopback_data,

  // Communication interface (send)
  output logic loopback_interface_valid,
  input  logic interface_loopback_ready,
  output interface_send_data_t loopback_interface_data,

  // Mailbox
  output logic loopback_mailbox_valid,
  input  logic mailbox_loopback_ready,
  output interface_receive_data_t loopback_mailbox_data,

  // Communication interface (receive)
  input  logic interface_loopback_valid,
  output logic loopback_interface_ready,
  input interface_send_data_t interface_loopback_data
);

  logic postoffice_destination_is_self;
  logic should_loopback;

  // Always connected
  assign loopback_interface_data = postoffice_loopback_data;

  always_comb begin : detect_loopback
    postoffice_destination_is_self = postoffice_loopback_data.message.meta.address == local_address;
    should_loopback = postoffice_loopback_valid & postoffice_destination_is_self;
  end

  always_comb begin : routing
    loopback_interface_valid = 0;
    loopback_postoffice_ready = 0;

    loopback_mailbox_valid = 0;
    loopback_interface_ready = 0;

    if (should_loopback) begin : connect_loopback
      loopback_postoffice_ready = mailbox_loopback_ready;
      loopback_mailbox_valid = postoffice_loopback_valid;

      loopback_mailbox_data = postoffice_loopback_data;
    end else begin : connect_interface
      loopback_interface_valid = postoffice_loopback_valid;
      loopback_postoffice_ready = interface_loopback_ready;

      loopback_mailbox_valid = interface_loopback_valid;
      loopback_interface_ready = mailbox_loopback_ready;

      loopback_mailbox_data = interface_loopback_data;
    end
  end

endmodule
