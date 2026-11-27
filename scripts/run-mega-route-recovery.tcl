# External driver: one unchanged sealed implementation recipe; collect reports in
# the routed design BEFORE the post-route phys_opt that failed on the old kit.
if {$argc != 2} {error {usage: sealed-kit fresh-implementation-output}}
lassign $argv kit root; set kit [file normalize $kit]; set root [file normalize $root]
if {[file exists $root] || ![file isfile [file join $kit CANDIDATE.sha256]] || ![string match {2024.2*} [version -short]]} {error {need fresh output, sealed kit, Vivado 2024.2}}
set_param general.maxThreads 2; set_param synth.maxThreads 2
set ::recovery_before_done 0; set ::recovery_root $root
proc recovery_before_physopt {command op} {
    set obj [file join $::recovery_root obj]
    if {$::recovery_before_done || ![file isfile [file join $obj routed_before_physopt.dcp]]} {return}
    if {$op ne {enter} || [lrange $command 1 end] ne {-directive Explore}} {error {unexpected physical optimization}}
    set dir [file join $obj review-before-physopt]; if {[file exists $dir]} {error {stale review}}; file mkdir $dir
    puts RECOVERY_BEFORE_PHYSOPT_REPORTS_BEGIN
    report_route_status -file [file join $dir route.rpt]
    report_timing_summary -report_unconstrained -file [file join $dir timing.rpt]
    check_timing -verbose -file [file join $dir coverage.rpt]
    set cpu [get_clocks clk_out1_harnessSysPLL]; if {[llength $cpu]!=1 || abs([get_property PERIOD $cpu]-5.714)>0.001} {error {wrong CPU clock}}
    report_timing -to $cpu -delay_type max -max_paths 40 -nworst 1 -input_pins -file [file join $dir cpu-max.rpt]
    report_cdc -details -file [file join $dir cdc.rpt]; report_drc -file [file join $dir drc.rpt]
    report_clock_interaction -file [file join $dir clocks.rpt]; report_bus_skew -file [file join $dir original-bus-skew.rpt]
    set ::recovery_before_done 1; puts RECOVERY_BEFORE_PHYSOPT_REPORTS_COLLECTED
}
trace add execution phys_opt_design enter recovery_before_physopt
set argv [list [file join $kit sources.f] [file join $kit shell xilinx common tcl] $root]; set argc 3
puts RECOVERY_SEALED_RECIPE_START
source [file join $kit implement.tcl]
if {!$::recovery_before_done} {error {expected pre-physopt reports not collected}}
