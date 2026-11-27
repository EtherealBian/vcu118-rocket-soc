# Isolated issue-count slice, fully registered ports, not a CPU implementation.
if {$argc != 1} {error {usage: <freshly generated fixture directory>}}
set dir [file normalize [lindex $argv 0]]
set_param general.maxThreads 2
foreach top {issue_ref issue_partial} {
 set out [file join $dir $top]; if {[file exists $out]} {error {refusing old run}}; file mkdir $out
 create_project -in_memory -part xcvu9p-flga2104-2L-e
 read_verilog -sv [file join $dir $top.sv]
 set x [open [file join $out clk.xdc] w]; puts $x {create_clock -name clk -period 5.714 [get_ports clk]};close $x
 read_xdc [file join $out clk.xdc]
 synth_design -top $top -part xcvu9p-flga2104-2L-e -mode out_of_context
 opt_design;place_design;route_design
 report_route_status -file [file join $out route.rpt]
 report_timing -from [all_registers] -to [all_registers] -max_paths 10 -file [file join $out setup.rpt]
 report_timing_summary -file [file join $out summary.rpt];report_utilization -file [file join $out util.rpt]
 close_project
}
puts ISSUE_SLICE_TWO_OOC_ROUTES_COMPLETE
