`ifndef XCTCMSG_NETWORKS__OPENPITON_SVH
`define XCTCMSG_NETWORKS__OPENPITON_SVH


`define XCTCMSG_NETWORK_OPENPITON_INTERFACE                \
  // NoC send                                              \
  output logic                                noc_out_val  \
, input  logic                                noc_out_rdy  \
, output openpiton_raw_noc_t                  noc_out_data \
                                                           \
  // NoC receive                                           \
, input  logic                                noc_in_val   \
, output logic                                noc_in_rdy   \
, input  openpiton_raw_noc_t                  noc_in_data

`define XCTCMSG_NETWORK_OPENPITON_ADAPTER openpiton_adapter

`endif // XCTCMSG_NETWORKS__OPENPITON_SVH
