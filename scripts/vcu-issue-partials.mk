# Separate private assembly: also override one pinned BOOM scheduling source.
# The tapeout assembly keeps the upstream recipe, including its selected project.
$(GENERATOR_CLASSPATH): $(VCU_BUFFER_CONFIG) $(VCU_BUFFER_PATCHED) $(VCU_ISSUE_PATCHED) $(VCU_BUFFER_MK)
define run_sbt_assembly
	cd $(base_dir) && $(SBT) ';project $(1); $(if $(filter $(GENERATOR_CLASSPATH),$(2)),set LocalProject("rocketchip") / Compile / unmanagedSources ~= { xs => xs.map(f => if (f.getCanonicalPath == "$(VCU_BUFFER_ORIGINAL)") file("$(VCU_BUFFER_PATCHED)") else f) }; set LocalProject("boom") / Compile / unmanagedSources ~= { xs => require(xs.count(f => f.getCanonicalPath == "$(VCU_ISSUE_ORIGINAL)") == 1); xs.map(f => if (f.getCanonicalPath == "$(VCU_ISSUE_ORIGINAL)") file("$(VCU_ISSUE_PATCHED)") else f) }; set Compile / unmanagedSources += file("$(VCU_BUFFER_CONFIG)");) set assembly / assemblyOutputPath := file("$(2)"); assembly' && touch $(2)
endef
