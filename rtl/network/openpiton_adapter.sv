import xctcmsg_pkg::*, xctcmsg_piton_pkg::*;

module openpiton_adapter (
  input  message_addr_t local_address,

  // Loopback interceptor (send)
  input  logic loopback_interface_valid,
  output logic interface_loopback_ready,
  input  interface_send_data_t loopback_interface_data,

  // Loopback interceptor (receive)
  output logic interface_loopback_valid,
  input  logic loopback_interface_ready,
  output interface_receive_data_t interface_loopback_data,

  // NoC interface
  openpiton_interface.FU network_interface
);

  openpiton_noc_t msg_out, msg_in;

  function automatic openpiton_msg_dst_x_t get_x_coordinate(input message_addr_t address);
    message_addr_t tmp = address % OPENPITON_X_TILES;
    return tmp[NOC_MSG_DST_X_WIDTH-1:0];
  endfunction

  function automatic openpiton_msg_dst_y_t get_y_coordinate(input message_addr_t address);
    message_addr_t tmp = address / OPENPITON_X_TILES;
    return tmp[NOC_MSG_DST_Y_WIDTH-1:0];
  endfunction

  always_comb begin : encode_out_message
    msg_out.parts.header.parts.reserved = 0;
    msg_out.parts.header.parts.length = NOC_MSG_PAYLOAD_LENGTH;
    msg_out.parts.header.parts.dst_fbits = 0;
    msg_out.parts.header.parts.dst_y = get_y_coordinate(loopback_interface_data.message.meta.address);
    msg_out.parts.header.parts.dst_x = get_x_coordinate(loopback_interface_data.message.meta.address);
    msg_out.parts.header.parts.dst_chipid = 0;

    msg_out.parts.payload.parts.source = local_address;
    msg_out.parts.payload.parts.tag = loopback_interface_data.message.meta.tag;
    msg_out.parts.payload.parts.data = loopback_interface_data.message.data;
  end

  always_comb begin : valrdy_out_message
    network_interface.noc_out_val = loopback_interface_valid;
    interface_loopback_ready = network_interface.noc_out_rdy;
    network_interface.noc_out_data = msg_out.raw;
  end

  always_comb begin : decode_in_message
    interface_loopback_data.message.meta.address = msg_in.parts.payload.parts.source;
    interface_loopback_data.message.meta.tag = msg_in.parts.payload.parts.tag;
    interface_loopback_data.message.data = msg_in.parts.payload.parts.data;
  end

  always_comb begin : valrdy_in_message
    interface_loopback_valid = network_interface.noc_in_val;
    network_interface.noc_in_rdy = loopback_interface_ready;
    msg_in.raw = network_interface.noc_in_data;
  end

endmodule
