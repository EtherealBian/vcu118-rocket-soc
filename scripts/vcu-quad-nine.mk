# Included after Chipyard Makefile. Only the private generator assembly gets these two source overrides.
# The tapeout assembly keeps the upstream recipe, including its selected project.
$(GENERATOR_CLASSPATH): $(VCU_BUFFER_CONFIG) $(VCU_BUFFER_PATCHED) $(VCU_DEEP_PATCHED) $(VCU_FE_PATCHED) $(VCU_BUFFER_MK)
define run_sbt_assembly
	cd $(base_dir) && $(SBT) ';project $(1); $(if $(filter $(GENERATOR_CLASSPATH),$(2)),set LocalProject("rocketchip") / Compile / unmanagedSources ~= { xs => xs.map(f => if (f.getCanonicalPath == "$(VCU_BUFFER_ORIGINAL)") file("$(VCU_BUFFER_PATCHED)") else if (f.getCanonicalPath == "$(VCU_DEEP_ORIGINAL)") file("$(VCU_DEEP_PATCHED)") else if (f.getCanonicalPath == "$(VCU_FE_ORIGINAL)") file("$(VCU_FE_PATCHED)") else f) }; set Compile / unmanagedSources += file("$(VCU_BUFFER_CONFIG)");) set assembly / assemblyOutputPath := file("$(2)"); assembly' && touch $(2)
endef
