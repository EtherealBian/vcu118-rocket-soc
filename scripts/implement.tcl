# Run from Windows Vivado, after a successful WSL elaboration.
if {$argc != 3} {error "usage: manifest upstream-board-scripts fresh-run-directory"}
lassign $argv mf scripts rundir
foreach v {mf scripts rundir} {set $v [file normalize [set $v]]}
if {[file exists [file join $rundir obj]]} {error "old run directory not allowed"}; file mkdir $rundir
set ipdir0 [file dirname $mf]
# Pinned generator writes exactly three scripts at manifest root, or under board/ in the portable kit. Never scan old runs.
set boardinputs [expr {[file exists [file join $ipdir0 board]] ? [file join $ipdir0 board] : $ipdir0}]
set ipfiles {}; foreach k {harnessSysPLL shell vcu118mig} {set found [glob -nocomplain -directory $boardinputs *.$k.vivado.tcl]; if {[llength $found] != 1} {error "expected one $k script under $boardinputs: $found"}; lappend ipfiles [lindex $found 0]}
set fd [open $mf r]; set body [read $fd]; close $fd; set wf [file join $rundir sources.windows.f]; set dest [open $wf w]; set count 0
foreach s [split $body "\n"] {set s [string trim $s]; if {$s eq {} || [string match {#*} $s]} continue
 if {[regexp {^/mnt/([a-z])/(.*)$} $s -> drive rest]} {set s "${drive}:/$rest"} elseif {[file pathtype $s] eq "relative"} {set s [file join $ipdir0 $s]}
 if {![file isfile $s]} {error "HDL source unavailable on Windows: $s"}; puts $dest [file normalize $s]; incr count
}; close $dest; if {$count<10} {error "suspiciously short RTL manifest"}
cd $rundir; set argv [list -top-module VCU118FPGATestHarness -F $wf -board vcu118 -ip-vivado-tcls [join $ipfiles { }]]
# Run the pinned upstream stages unchanged. Its final report.tcl exits the entire
# interpreter on negative WNS, so gather route/CDC evidence before that script.
set scriptdir $scripts
foreach stage {prologue init synth opt place route} {puts "VCU118_STAGE=$stage"; source [file join $scriptdir $stage.tcl]}
file mkdir [file join $rundir obj report]
set r [file join $rundir obj report]; report_route_status -file [file join $r route-status.rpt]; report_timing_summary -report_unconstrained -file [file join $r full-timing.rpt]; check_timing -verbose -file [file join $r check-timing.rpt]; report_cdc -details -file [file join $r cdc.rpt]; report_clock_interaction -file [file join $r clock-interaction.rpt]
report_pulse_width -file [file join $r pulse-width.rpt]; report_methodology -file [file join $r methodology.rpt]; report_clocks -file [file join $r routed-clocks.rpt]; report_utilization -file [file join $r routed-utilization.rpt]; report_drc -file [file join $r routed-drc.rpt]
foreach d {max min} {set paths [get_timing_paths -quiet -delay_type $d -max_paths 1]; if {![llength $paths]} {error "no $d timing paths"}; set slack [get_property SLACK $paths]; puts "ROUTED_${d}_SLACK_NS=$slack"; if {$slack<0} {error "timing violation"}}
foreach stage {bitstream report} {puts "VCU118_STAGE=$stage"; source [file join $scriptdir $stage.tcl]}
if {![file isfile [file join $rundir obj VCU118FPGATestHarness.bit]]} {error "no bitstream"}
puts "BIT_WRITTEN_SETUP_HOLD_NONNEGATIVE_REVIEW_CDC_AND_COVERAGE"
