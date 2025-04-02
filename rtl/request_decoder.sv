import xctcmsg_pkg::*;

module request_decoder (
  // RR-stage
  input  logic rr_request_decoder_valid,
  output logic request_decoder_rr_ready,
  input  request_data_t rr_request_decoder_data,

  // Send queue
  output logic request_decoder_send_queue_valid,
  input  logic send_queue_request_decoder_ready,
  output send_queue_data_t request_decoder_send_queue_data,

  // Receive queue
  output logic request_decoder_receive_queue_valid,
  input  logic receive_queue_request_decoder_ready,
  output receive_queue_data_t request_decoder_receive_queue_data
);

  typedef enum {
    REQUEST_TARGET_INVALID,
    REQUEST_TARGET_PIPELINE_SEND,
    REQUEST_TARGET_PIPELINE_RECV
  } request_target_t;

  // Signals for request discrimination
  request_type_t request_type;
  request_target_t request_target_pipeline;

  always_comb begin : request_discrimination
    request_type = request_type_t'(rr_request_decoder_data.funct3);

    case (request_type)
      REQUEST_TYPE_SEND  : request_target_pipeline = REQUEST_TARGET_PIPELINE_SEND;
      REQUEST_TYPE_RECV  : request_target_pipeline = REQUEST_TARGET_PIPELINE_RECV;
      REQUEST_TYPE_AVAIL : request_target_pipeline = REQUEST_TARGET_PIPELINE_RECV;
      default            : request_target_pipeline = REQUEST_TARGET_INVALID;
    endcase
  end

  always_comb begin : rr_stage
    case (request_target_pipeline)
      REQUEST_TARGET_PIPELINE_SEND : request_decoder_rr_ready = send_queue_request_decoder_ready;
      REQUEST_TARGET_PIPELINE_RECV : request_decoder_rr_ready = receive_queue_request_decoder_ready;
      default                      : request_decoder_rr_ready = 0;
    endcase
  end

  always_comb begin : send_queue
    request_decoder_send_queue_valid =
      rr_request_decoder_valid & request_target_pipeline == REQUEST_TARGET_PIPELINE_SEND;

    request_decoder_send_queue_data.message.meta = rr_request_decoder_data.rs2;
    request_decoder_send_queue_data.message.data = rr_request_decoder_data.rs1;
    request_decoder_send_queue_data.register = rr_request_decoder_data.rd;
    request_decoder_send_queue_data.passthrough = rr_request_decoder_data.passthrough;
  end

  always_comb begin : receive_queue
    request_decoder_receive_queue_valid =
      rr_request_decoder_valid & request_target_pipeline == REQUEST_TARGET_PIPELINE_RECV;

    request_decoder_receive_queue_data.is_avail = request_type == REQUEST_TYPE_AVAIL;
    request_decoder_receive_queue_data.meta = rr_request_decoder_data.rs1;
    request_decoder_receive_queue_data.meta_mask = ~rr_request_decoder_data.rs2;
    request_decoder_receive_queue_data.register = rr_request_decoder_data.rd;
    request_decoder_receive_queue_data.passthrough = rr_request_decoder_data.passthrough;
  end

endmodule
