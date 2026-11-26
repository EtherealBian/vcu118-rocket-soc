# Preserve the first routed run, inputs and constraints. Only apply physical hold fixes.
if {$argc != 2} {error "usage: input-routed.dcp new-output-directory"}; lassign $argv dcp out
set dcp [file normalize $dcp]; set out [file normalize $out]; if {[file exists $out]} {error "fresh output required"}; file mkdir $out; cd $out; open_checkpoint $dcp
phys_opt_design -aggressive_hold_fix
report_timing_summary -report_unconstrained -file timing.rpt; report_route_status -file route.rpt; report_utilization -file utilization.rpt; check_timing -verbose -file check-timing.rpt; write_checkpoint -force dot4-routed.dcp
foreach k {max min} {set p [get_timing_paths -delay_type $k -max_paths 1]; if {![llength $p]} {error "no $k paths"}; set s [get_property SLACK $p]; puts "OOC_${k}_SLACK_NS=$s"; if {$s<0} {error "$k timing failed"}}
puts "DOT4_ROUTED_OOC_100MHZ_NOT_SOC_SIGNOFF"
