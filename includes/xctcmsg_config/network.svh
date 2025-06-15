`ifndef XCTCMSG_CONFIG__NETWORK_SVH
`define XCTCMSG_CONFIG__NETWORK_SVH

// Network configuration -> Parameters corresponding to the network that
//                          connects all cores.
`ifdef XCTCMSG_NETWORK_BUS
  `define XCTCMSG_NETWORK_INTERFACE bus_interface
  `define XCTCMSG_NETWORK_ADAPTER   bus_adapter
`elsif XCTCMSG_NETWORK_OPENPITON
  `define XCTCMSG_NETWORK_INTERFACE openpiton_interface
  `define XCTCMSG_NETWORK_ADAPTER   openpiton_adapter
`else
  `error "Missing or unrecognized `XCTCMSG_NETWORK_* define"
`endif

`endif // XCTCMSG_CONFIG__NETWORK_SVH
