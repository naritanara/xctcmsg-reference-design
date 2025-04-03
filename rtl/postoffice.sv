import xctcmsg_pkg::*;

module postoffice #(
    parameter MAX_HARTID = 64
) (
    input clk,
    input rst_n,
    input flush,

    // Send queue
    input logic send_queue_postoffice_valid,
    output logic postoffice_send_queue_ready,
    input send_queue_data_t send_queue_postoffice_data,

    // Writeback arbiter
    output logic postoffice_writeback_arbiter_valid,
    input logic writeback_arbiter_postoffice_acknowledge,
    output writeback_arbiter_data_t postoffice_writeback_arbiter_data,

    // Loopback interceptor
    output logic postoffice_loopback_valid,
    input logic loopback_postoffice_ready,
    output interface_send_data_t postoffice_loopback_data,

    // Commit safety unit
    output commit_safety_request_t postoffice_csu_request,
    input logic csu_postoffice_grant
);

    // Writeback holding registers
    logic writeback_valid;
    writeback_arbiter_data_t writeback_data;

    // Writeback holding registers operations
    logic writeback_allocate_valid;
    logic writeback_deallocate_valid;

    // Writeback holding registers status
    logic writeback_allocatable;
    assign writeback_allocatable = !writeback_valid | writeback_deallocate_valid;

    // Destination validation signals
    logic destination_valid;
    logic destination_is_out_of_range;

    always_ff @(posedge clk, negedge rst_n) begin
        if (!rst_n | flush) begin
            writeback_valid <= 0;
        end else begin
            if (writeback_allocate_valid & writeback_allocatable) begin
                writeback_valid <= 1;
                writeback_data.register <= send_queue_postoffice_data.register;
                writeback_data.value <= destination_valid ? 1 : 0;
                writeback_data.passthrough <= send_queue_postoffice_data.passthrough;
            end else if (writeback_deallocate_valid) begin
                writeback_valid <= 0;
            end
        end
    end

    always_comb begin : destination_validation
        destination_is_out_of_range = unsigned'(send_queue_postoffice_data.message.meta.address) > unsigned'(MAX_HARTID);
        destination_valid = !destination_is_out_of_range;
    end

    logic wants_to_send;
    logic sending_now;

    always_comb begin : interface_communication_predicates
        wants_to_send = send_queue_postoffice_valid & destination_valid;
        sending_now   = postoffice_loopback_valid & loopback_postoffice_ready;
    end

    always_comb begin : request_acceptance
        postoffice_send_queue_ready = (sending_now | !wants_to_send) & writeback_allocatable;
        writeback_allocate_valid = postoffice_send_queue_ready & send_queue_postoffice_valid;
    end

    always_comb begin : interface_communication
        postoffice_loopback_valid = wants_to_send & writeback_allocatable & csu_postoffice_grant;
        postoffice_loopback_data.message = send_queue_postoffice_data.message;
    end

    always_comb begin : writeback_holding_registers_popping
        postoffice_writeback_arbiter_valid = writeback_valid;
        postoffice_writeback_arbiter_data = writeback_data;

        writeback_deallocate_valid = writeback_arbiter_postoffice_acknowledge;
    end

`ifdef XCTCMSG_SARGANTANA
    always_comb begin : pass_gl_index_to_csu
        postoffice_csu_request.payload = send_queue_postoffice_data.passthrough.gl_index;
    end
`endif

endmodule
