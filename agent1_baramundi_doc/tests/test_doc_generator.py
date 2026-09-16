from src import doc_generator

# ---- _default_job_name: found during a bug-hunt review. Baramundi's own
# export convention names the .bds file generically (this repo's own
# sample data literally has an "Install.bds" for the Adobe job) - the
# parent folder is what actually identifies the job. Defaulting to the
# bare filename stem meant two different jobs sharing that generic
# filename would silently overwrite each other's output doc.


def test_default_job_name_uses_the_parent_folder_not_the_generic_filename():
    assert doc_generator._default_job_name(
        "sample_inputs/Adobe_Acrobat_Reader_DC/Install.bds"
    ) == "Adobe_Acrobat_Reader_DC"


def test_default_job_name_distinguishes_two_jobs_sharing_the_same_filename():
    # This exact collision is real, not hypothetical - both of this repo's
    # sample jobs' actual files are named "Install*.bds".
    adobe = doc_generator._default_job_name("sample_inputs/Adobe_Acrobat_Reader_DC/Install.bds")
    other = doc_generator._default_job_name("sample_inputs/Some_Other_App/Install.bds")
    assert adobe != other


def test_default_job_name_falls_back_to_stem_with_no_parent_folder():
    assert doc_generator._default_job_name("Install.bds") == "Install"
