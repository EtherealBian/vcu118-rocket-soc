# Standalone pair comparison, serial, when vendor implementation tools are idle.
# Check CANDIDATE.sha256 before and after. No bitstream or device operations.
if {$argc != 2} {error {usage: prepared-case-directory fresh-output-directory}}
lassign $argv dir out; set dir [file normalize $dir]; set out [file normalize $out]
if {[file exists $out] || ![regexp {^(64|65)-(stock|lvt)$} [file tail $dir] -> width role]} {error {unexpected case or existing output}}
if {![string match {2024.2*} [version -short]]} {error {requires Vivado 2024.2}}
file mkdir $out; cd $out; set_param general.maxThreads 2
set part xcvu9p-flga2104-2L-e; create_project -in_memory -part $part
if {$role eq "lvt"} {read_verilog [file join $dir vcu_lvt_regfile.v]}
set parent [expr {$width==64?"RegisterFileSynthesizable_1":"RegisterFileSynthesizable"}]
read_verilog -sv [file join $dir regfile_128x${width}.sv]; read_verilog -sv [file join $dir ${parent}.sv]
read_verilog [file join $dir rf_boundary.v]; read_xdc [file join $dir rf.xdc]
synth_design -top rf_boundary -part $part -mode out_of_context
set clock [get_clocks rf_clk]; if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-5.714)>0.0001} {error {clock not constrained}}
report_utilization -file synth-util.rpt; opt_design; place_design; route_design
report_route_status -file route.rpt; report_timing_summary -report_unconstrained -file summary.rpt
report_drc -file drc.rpt; check_timing -verbose -file coverage.rpt
report_utilization -file util.rpt; report_utilization -hierarchical -hierarchical_depth 5 -file hier.rpt
# Exclude external zero-delay paths from the quoted path table. Save normal
# timing summary separately; full OOC interface isn't a physical board clock.
set regs [all_registers -clock $clock]; if {[llength $regs]<128} {error {boundary logic missing}}
foreach delay {max min} {
 set paths [get_timing_paths -delay_type $delay -from $regs -to $regs -max_paths 10 -nworst 1]
 if {[llength $paths]!=10} {error {expected ten timed register endpoints}}
 report_timing -of_objects $paths -file registers-$delay.rpt
 set fd [open registers-$delay.tsv {WRONLY CREAT EXCL}]; puts $fd "slack_ns\tstart\tend"
 foreach p $paths {puts $fd [join [list [get_property SLACK $p] [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]] "\t"]}; close $fd
}
close_project; puts REGFILE_OOC_REPORTS_READY_NOT_SOC_TIMING
