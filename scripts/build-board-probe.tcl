# Vivado 2024.2 non-project, fresh directory. Does not touch a board.
if {$argc!=1} {error {usage: fresh-run-dir}}
if {[version -short] ne "2024.2"} {error {expected Vivado 2024.2}}
set root [file dirname [file dirname [file normalize [info script]]]]; set src [file join $root rtl boardprobe]
set out [file normalize [lindex $argv 0]]; if {[file exists $out]} {error {refusing to reuse a run}}; file mkdir $out; cd $out
set_param general.maxThreads 2
read_verilog -sv [list $src/probe_protocol.sv $src/vcu118_probe.sv]
synth_design -top vcu118_probe -part xcvu9p-flga2104-2L-e -flatten_hierarchy none
foreach p {rx_meta_reg/D lock_meta_reg/D rx_sync_reg/D lock_sync_reg/D mmcm/LOCKED protocol/tx_reg/C} {if {[llength [get_pins -quiet $p]]!=1} {error "missing constraint object $p"}}
set lock_d [get_pins lock_meta_reg/D]
set lock_drivers [get_pins -of_objects [get_nets -of_objects $lock_d] -filter {DIRECTION == OUT}]
if {[llength $lock_drivers]!=1 || [get_property NAME $lock_drivers] ne "mmcm/LOCKED"} {error "unexpected lock synchronizer D driver: $lock_drivers"}
read_xdc $src/probe.xdc
opt_design; place_design; route_design; write_checkpoint probe-routed.dcp
report_route_status -file route.rpt; report_timing_summary -report_unconstrained -file timing.rpt; check_timing -verbose -file check.rpt
report_cdc -details -file cdc.rpt; report_exceptions -coverage -file exceptions.rpt; report_io -file io.rpt; report_clocks -file clocks.rpt; report_utilization -file resources.rpt; report_drc -file drc.rpt; report_methodology -file methodology.rpt
foreach {m s} {rx_meta_reg rx_sync_reg lock_meta_reg lock_sync_reg} {
    foreach c [list $m $s] {if {![get_property ASYNC_REG [get_cells $c]]} {error "lost ASYNC_REG on $c"}}
    set fan [all_fanout -flat -endpoints_only -from [get_pins $m/Q]]; if {[llength $fan]!=1 || $fan ne "$s/D"} {error "unexpected sync chain: $fan"}
    set p [get_timing_paths -from [get_cells $m] -to [get_cells $s] -max_paths 1]; if {[llength $p]!=1 || [get_property SLACK $p]<0} {error {synchronizer has no timed settling path}}
}
set c [get_clocks -of_objects [get_pins protocol/tx_reg/C]]; if {[llength $c]!=1 || abs([get_property PERIOD $c]-10.0)>0.001} {error "unexpected fabric clock: $c"}
foreach d {max min} {set p [get_timing_paths -delay_type $d -max_paths 1]; if {[llength $p]!=1 || [get_property SLACK $p]<0} {error "$d timing violation"}}
if {[llength [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]]} {error {routed DRC error}}
write_bitstream probe.bit; puts VCU118_PROBE_BIT_WRITTEN
