# Recover diagnostic evidence from the original placed checkpoint after an
# interrupted post-route optimization. No additional optimization, no bit write.
if {$argc != 2} {error "usage: resume-route.tcl <post_place.dcp> <fresh-run>"}; lassign $argv src out
set src [file normalize $src]; set out [file normalize $out]; set aux [file join [file dirname [file normalize [info script]]] diagnose-routed.tcl]
if {![file isfile $src] || [file exists $out]} {error "missing checkpoint or output exists"}; file mkdir $out; cd $out
set_param general.maxThreads 2
open_checkpoint $src
if {![string equal -nocase [get_property PART [current_design]] "xcvu9p-flga2104-2L-e"]} {error "not VCU118 XCVU9P"}
source $aux
vcu_endpoint_reports [file join $out placed-estimates]; puts PLACED_TOPOLOGY_ESTIMATES_ONLY
route_design -directive Explore
set obj [file join $out obj]; file mkdir $obj; write_checkpoint [file join $obj post_route.dcp]; puts ROUTED_DCP_SAVED_BEFORE_REPORTS
set r [file join $obj report]; file mkdir $r
report_route_status -file [file join $r route-status.rpt]; report_timing_summary -report_unconstrained -file [file join $r full-timing.rpt]
vcu_endpoint_reports [file join $out routed-endpoints]
check_timing -verbose -file [file join $r check-timing.rpt]; report_cdc -details -file [file join $r cdc.rpt]; report_clock_interaction -file [file join $r clock-interaction.rpt]; report_pulse_width -file [file join $r pulse-width.rpt]; report_methodology -file [file join $r methodology.rpt]; report_clocks -file [file join $r routed-clocks.rpt]; report_utilization -file [file join $r routed-utilization.rpt]; report_drc -file [file join $r routed-drc.rpt]
puts ROUTED_DIAGNOSTICS_ONLY_NO_BIT
