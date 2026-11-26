# Standalone IP estimate. No VCU118 pin/board constraints and not integrated in Rocket.
if {$argc != 2} {error "usage: source.sv fresh-output-directory"}; lassign $argv rtl out
set rtl [file normalize $rtl]; set out [file normalize $out]; if {[file exists $out]} {error "output already exists"}; file mkdir $out; cd $out
set dev xcvu9p-flga2104-2L-e
create_project -in_memory -part $dev
set_property target_language Verilog [current_project]
set f [open dot.xdc w]; puts $f {create_clock -name accel_clk -period 10.000 [get_ports clk]}; puts $f {set_input_delay -clock accel_clk -max 2.0 [get_ports {rst in_valid out_ready a[*] b[*]}]}; puts $f {set_input_delay -clock accel_clk -min 0.0 [get_ports {rst in_valid out_ready a[*] b[*]}]}; puts $f {set_output_delay -clock accel_clk -max 2.0 [get_ports {in_ready out_valid result[*]}]}; puts $f {set_output_delay -clock accel_clk -min 0.0 [get_ports {in_ready out_valid result[*]}]}; close $f
read_verilog -sv $rtl; read_xdc dot.xdc; synth_design -top dot4_i8 -part $dev -mode out_of_context; opt_design; place_design; route_design
set holdpath [get_timing_paths -quiet -delay_type min -max_paths 1]; if {[llength $holdpath] && [get_property SLACK $holdpath] < 0} {puts "POST_ROUTE_HOLD_OPT"; phys_opt_design -aggressive_hold_fix}
report_timing_summary -report_unconstrained -file timing.rpt; report_utilization -file utilization.rpt; report_route_status -file route.rpt; check_timing -verbose -file check-timing.rpt; report_drc -file drc.rpt; write_checkpoint -force dot4-routed.dcp
foreach kind {max min} {set path [get_timing_paths -quiet -delay_type $kind -max_paths 1]; if {[llength $path]!=1} {error "missing timing paths"}; set val [get_property SLACK $path]; puts "OOC_${kind}_SLACK_NS=$val"; if {$val < 0} {error "$kind negative slack"}}
puts "DOT4_ROUTED_OOC_100MHZ_NOT_SOC_SIGNOFF"
