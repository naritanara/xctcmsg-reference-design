import xctcmsg_pkg::*, xctcmsg_piton_pkg::*;

interface openpiton_interface ();
  // NoC send
  logic noc_out_val;
  logic noc_out_rdy;
  openpiton_raw_noc_t noc_out_data;

  // NoC receive
  logic noc_in_val;
  logic noc_in_rdy;
  openpiton_raw_noc_t noc_in_data;

  modport FU (
    output noc_out_val,
    input noc_out_rdy,
    output noc_out_data,
    input noc_in_val,
    output noc_in_rdy,
    input noc_in_data
  );

  modport NET (
    input noc_out_val,
    output noc_out_rdy,
    input noc_out_data,
    output noc_in_val,
    input noc_in_rdy,
    output noc_in_data
  );
endinterface
