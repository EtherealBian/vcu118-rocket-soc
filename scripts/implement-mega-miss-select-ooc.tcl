# Compare only the integer-queue valid cones at a common registered boundary.
if {$argc != 2} {error {usage: proof-directory fresh-output}}
lassign $argv in out; set in [file normalize $in]; set out [file normalize $out]
if {[file exists $out] || ![string match {2024.2*} [version -short]]} {error {requires Vivado 2024.2 and fresh output}}
file mkdir $out; set_param general.maxThreads 2
proc sample {f group slot start end} {
    set p [get_timing_paths -quiet -from $start -to $end -delay_type max -max_paths 1]
    if {[llength $p]!=1} {error "missing $group $slot"}
    puts $f [join [list $group $slot [get_property SLACK $p] [get_property DATAPATH_DELAY $p] [get_property LOGIC_LEVELS $p] [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]] "\t"]
}
foreach n {stock candidate} {
    set work [file join $out $n]; file mkdir $work; cd $work
    create_project -in_memory -part xcvu9p-flga2104-2L-e
    read_verilog [file join $in $n.v]; read_verilog [file join $in boundary.v]; read_xdc [file join $in clock.xdc]
    synth_design -mode out_of_context -top miss_boundary -part xcvu9p-flga2104-2L-e
    opt_design; place_design; route_design
    report_route_status -file route.rpt; report_timing_summary -report_unconstrained -file timing.rpt; report_utilization -file util.rpt
    set clk [get_clocks cpu]; set miss [get_cells -quiet q_miss_reg]
    if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-5.714)>0.0001 || [llength $miss]!=1} {error {missing miss register or constraint}}
    set all [all_registers -clock $clk]; set f [open paths.tsv {WRONLY CREAT EXCL}]
    puts $f "group\tslot\tslack_ns\tdata_ns\tlevels\tfrom\tto"
    for {set i 0} {$i<40} {incr i} {
        foreach bus {qm qk} {
            set target [get_cells -quiet [list [format {%s_reg[%d]} $bus $i]]]
            if {[llength $target]!=1} {error "no unique $bus/$i capture"}
            set d [get_pins $target/D]; sample $f all-$bus $i $all $d
            if {$bus eq "qm" && $i==39} {
                if {[llength [get_timing_paths -quiet -from $miss -to $d -delay_type max -max_paths 1]]} {error {unexpected miss path to dispatch-only slot}}
            } else {sample $f miss-$bus $i $miss $d}
        }
    }
    close $f; write_checkpoint registers-routed.dcp; close_project; puts "INT_MISS_OOC_CASE_COLLECTED $n"
}
puts INT_MISS_OOC_PAIR_COLLECTED_NOT_SOC
