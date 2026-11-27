# Supplemental diagnostics for the sealed four-wide post-route checkpoint, including
# timing failures. Preflight the checkpoint and log with review-mega-routed-paths.py.
# No new constraints, implementation changes, writes to the DCP or device operations.
if {$argc != 2} {error {usage: post_route.dcp fresh-output-directory}}
lassign $argv dcp out
set dcp [file normalize $dcp]; set out [file normalize $out]
if {[file tail $dcp] ne "post_route.dcp" || ![file isfile $dcp] || [file exists $out]} {error {expected final checkpoint and fresh output}}
set_param general.maxThreads 2
open_checkpoint $dcp
set sys clk_out1_harnessSysPLL
foreach name [list $sys mmcm_clkout0] ns [list [expr {1000.0/175}] 5.0] {
 set c [get_clocks $name]
 if {[llength $c]!=1 || abs([get_property PERIOD $c]-$ns)>0.001} {error "unexpected clock: $name"}
}
file mkdir $out
# Report exceptions separately: fully ignored constraints and ignored individual
# objects are different reports. Compare applied coverage to the original XDC.
foreach {option name} {-coverage coverage -ignored ignored -ignored_objects ignored-objects} {
 report_exceptions $option -file [file join $out exceptions-$name.rpt]
}
report_waivers -file [file join $out waiver-definitions.rpt]
report_cdc -details -show_waiver -file [file join $out cdc-with-waivers.rpt]
report_drc -waived -file [file join $out waived-drc.rpt]
report_methodology -waived -file [file join $out waived-methodology.rpt]
report_utilization -slr -file [file join $out utilization-by-slr.rpt]
report_utilization -hierarchical -hierarchical_depth 12 -file [file join $out utilization-by-instance.rpt]
report_high_fanout_nets -slr -timing -max_nets 40 -file [file join $out high-fanout-by-slr.rpt]
report_design_analysis -congestion -min_congestion_level 3 -file [file join $out congestion.rpt]
foreach k {max min} {
 set paths [get_timing_paths -to [get_clocks $sys] -delay_type $k -max_paths 40 -nworst 1]
 if {[llength $paths]!=40} {error "incomplete CPU $k path sample"}
 report_design_analysis -timing -of_timing_paths $paths -file [file join $out cpu-$k-characteristics.rpt]
 set f [open [file join $out cpu-$k.tsv] {WRONLY CREAT EXCL}]; puts $f "slack_ns\tstart\tend"
 foreach path $paths {puts $f [join [list [get_property SLACK $path] [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path]] "\t"]}; close $f
}
close_design; puts FOUR_WIDE_ROUTED_DIAGNOSTICS_COLLECTED_NOT_SIGNOFF
