import xctcmsg_pkg::*;

module mbox #(
    parameter SIZE = 4,
    localparam INDEX_WIDTH = $clog2(SIZE)
) (
    input clk,
    input rst_n,
    input flush,

    // Receive queue
    input logic receive_queue_mailbox_valid,
    output logic mailbox_receive_queue_ready,
    input receive_queue_data_t receive_queue_mailbox_data,

    // Writeback arbiter
    output logic mailbox_writeback_arbiter_valid,
    input logic writeback_arbiter_mailbox_acknowledge,
    output writeback_arbiter_data_t mailbox_writeback_arbiter_data,

    // Loopback interceptor
    input logic loopback_mailbox_valid,
    output logic mailbox_loopback_ready,
    input interface_receive_data_t loopback_mailbox_data,

    // Commit safety unit
    output commit_safety_request_t mailbox_csu_request,
    input logic csu_mailbox_grant
);

    // Message buffers
    logic [SIZE-1:0] message_valid;
    message_t [SIZE-1:0] message_data;

    // Message buffers operations
    logic message_allocate_valid;
    logic [INDEX_WIDTH-1:0] message_allocate_index;
    logic message_deallocate_valid;
    logic [INDEX_WIDTH-1:0] message_deallocate_index;

    // Message buffers operations status
    logic message_requests_do_replace;

    always_comb begin : message_buffers_operations_status
        message_requests_do_replace =
            message_allocate_valid & message_deallocate_valid
            & (message_allocate_index == message_deallocate_index);
    end

    // Message buffers status
    logic free_message_cells;
    logic [INDEX_WIDTH-1:0] next_free_message_cell;

    always_comb begin : message_buffer_status
        free_message_cells = !(&message_valid);
        next_free_message_cell = 0;

        for (integer i = 0; i < SIZE; i = i + 1) begin
            if (!message_valid[i]) begin
                next_free_message_cell = i[INDEX_WIDTH-1:0];
                break;
            end
        end
    end

    always_comb begin : message_buffers_input
        message_allocate_valid = loopback_mailbox_valid & free_message_cells;
        message_allocate_index = next_free_message_cell;

        mailbox_loopback_ready = free_message_cells;
    end

    always_ff @(posedge clk, negedge rst_n) begin : message_buffers_registers
        if (!rst_n) begin
            message_valid <= 0;
        end else begin
            if (message_allocate_valid) begin
                message_valid[message_allocate_index] <= 1;
                message_data[message_allocate_index]  <= loopback_mailbox_data.message;
            end

            if (message_deallocate_valid && !message_requests_do_replace) begin
                message_valid[message_deallocate_index] <= 0;
            end
        end
    end

    // Request holding registers
    logic request_valid;
    receive_queue_data_t request_data;
    logic request_solved;

    // Request holding registers operations
    logic request_allocate_valid;
    logic request_deallocate_valid;

    // Request holding registers status
    logic request_allocatable;
    assign request_allocatable = !request_valid | request_deallocate_valid;

    // Serving receive queue / writeback arbiter
    always_comb begin
        mailbox_receive_queue_ready = csu_mailbox_grant & request_allocatable;
        request_allocate_valid = receive_queue_mailbox_valid & mailbox_receive_queue_ready;
    end

    always_ff @(posedge clk, negedge rst_n) begin : pending_request_register
        if (!rst_n | flush) begin
            request_valid  <= 0;
            request_solved <= 0;
        end else begin
            if (request_allocate_valid & request_allocatable) begin
                request_valid  <= 1;
                request_data   <= receive_queue_mailbox_data;
                request_solved <= 0;
            end else if (request_deallocate_valid) begin
                request_valid <= 0;
            end
        end
    end

    // Request resolution
    message_metadata_t [SIZE-1:0] message_metadata_masked;
    message_metadata_t request_metadata_masked;
    logic any_match;
    logic [INDEX_WIDTH-1:0] match_index;

    always_comb begin : request_resolution_buffer_controls
        request_deallocate_valid = request_valid & writeback_arbiter_mailbox_acknowledge;
        message_deallocate_valid = request_valid & writeback_arbiter_mailbox_acknowledge & !request_data.is_avail;
        message_deallocate_index = match_index;
    end

    always_comb begin : metadata_masking
        for (integer i = 0; i < SIZE; i = i + 1) begin
            message_metadata_masked[i] = message_data[i].meta & request_data.meta_mask;
        end

        request_metadata_masked = request_data.meta & request_data.meta_mask;
    end

    always_comb begin : metadata_matching
        any_match   = 0;
        match_index = 0;

        for (integer i = 0; i < SIZE; i = i + 1) begin
            if (message_valid[i] && message_metadata_masked[i] == request_metadata_masked) begin
                any_match   = 1;
                match_index = i[INDEX_WIDTH-1:0];
                break;
            end
        end
    end

    always_comb begin : request_resolution
        mailbox_writeback_arbiter_valid = 0;
        mailbox_writeback_arbiter_data.value = 0;

        if (request_valid) begin
            if (request_data.is_avail) begin
                mailbox_writeback_arbiter_valid = 1;
                mailbox_writeback_arbiter_data.value = any_match ? 1 : 0;
            end else if (any_match) begin
                mailbox_writeback_arbiter_valid = 1;
                mailbox_writeback_arbiter_data.value = message_data[match_index].data;
            end
        end

        mailbox_writeback_arbiter_data.passthrough = request_data.passthrough;
    end

`ifdef XCTCMSG_SARGANTANA
    always_comb begin : pass_gl_index_to_csu
        mailbox_csu_request.payload = receive_queue_mailbox_data.passthrough.gl_index;
    end
`endif

endmodule
