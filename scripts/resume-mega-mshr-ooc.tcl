# Resume a verified optimized OOC in two fresh Vivado processes; no device access.
if {$argc != 4 || ![string match {2024.2*} [version -short]]} {error {usage: place|route stock|class_local|split_rsp input-DCP fresh-output}}
lassign $argv stage name input out; set input [file normalize $input]; set out [file normalize $out]
if {$stage ni {place route} || $name ni {stock class_local split_rsp} || [file exists $out] || ![file isfile $input]} {error {bad stage, case, input, or stale output}}
set_param general.maxThreads 1
file mkdir $out; cd $out
# In checkpoint mode the design name is synthetic and fileset TOP can be empty.
# Use the supplied DCP's manifest for top/OOC; check device and endpoints live.
set tar [file join $::env(SystemRoot) System32 tar.exe]
set manifest [exec $tar -xOf $input dcp.xml]
foreach {tag val} {Top boundary OutOfContext 1 Part xcvu9p-flga2104-2L-e BUILD_NUMBER 5239630} {
    set pat [format {<%s Name="([^"]+)"/>} $tag]
    if {[regexp -all -- $pat $manifest] != 1 || ![regexp -- $pat $manifest -> actual] || $actual ne $val} {error "wrong local checkpoint $tag"}
}
open_checkpoint $input
if {[get_property PART [current_design]] ne {xcvu9p-flga2104-2L-e} || [llength [get_ports -quiet clk]]!=1} {error {wrong live part or clock port}}
for {set i 0} {$i<3} {incr i} {
    set cap [get_cells -quiet [list [format {result_reg[%d]} $i]]]
    if {[llength $cap]!=1 || [llength [get_pins -quiet $cap/D]]!=1} {error "wrong live capture $i"}
}
set clk [get_clocks cpu]; if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-5.714)>0.0001} {error {wrong cpu clock}}
if {$stage eq {place}} {
    place_design
    write_checkpoint local-placed.dcp
    puts "MSHR_RESUMED_PLACED $name"
} else {
    route_design
    write_checkpoint local-routed.dcp
    report_route_status -file route.rpt
    report_timing_summary -report_unconstrained -file timing.rpt
    report_utilization -file util.rpt
    set f [open paths.tsv {WRONLY CREAT EXCL}]; puts $f "group\toutput\tslack_ns\tdata_ns\tlevels\tfrom\tto"
    proc sample {f name idx src d} {
        if {![llength $src]} {error "no sources for $name"}
        set p [get_timing_paths -quiet -from $src -to $d -delay_type max -max_paths 1]; if {[llength $p]!=1} {error "missing path $name $idx"}
        report_timing -of_objects $p -file [format {path-%s-%d.rpt} $name $idx]
        puts $f [join [list $name $idx [get_property SLACK $p] [get_property DATAPATH_DELAY $p] [get_property LOGIC_LEVELS $p] [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]] "\t"]
    }
    set all [all_registers -clock $clk]
    for {set i 0} {$i<3} {incr i} {
        set capture [get_cells -quiet [list [format {result_reg[%d]} $i]]]; if {[llength $capture]!=1} {error "bad capture $i"}; set d [get_pins $capture/D]
        sample $f all $i $all $d
        if {$i==2} {
            foreach {label patt} {branch q_dc_io_lsu_brupdate_b1_mispredict_mask_reg* address1 q_dc_s2_req_1_addr_reg* state q_m?_state_reg* rpq q_q?_*_reg*} {
                set src [get_cells -hierarchical -quiet -filter "IS_SEQUENTIAL == 1 && NAME =~ $patt"]
                sample $f $label $i $src $d
            }
        }
    }
    close $f; puts "MSHR_RESUMED_ROUTED $name"
}
