# Vidchecker Template Import

<!-- GENERATED FILE - do not edit by hand.
     Source: scripts/import_vidchecker_templates.py over
     presets/_sources/vidchecker/. Regenerate by re-running the script. -->

Vidchecker 8.2.2 template export captured 2026-07-27 from the
production instance. One draft preset per template; checks without an
implemented catalogue parameter are listed in each preset's header and
counted below. Thresholds are placeholders pending human approval
(handoff section 30, ADR-025).

| Vidchecker id | Template | Outcome | Rules | Uncovered checks |
|---|---|---|---|---|
| 1 | -  File Info | skipped: no translatable checks | 0 | 0 |
| 2 | - ARD_ZDF_HDF01a 1080i25 8 Track XDCAM HD422 V1.2 | imported: presets/library/vidchecker/vc002_ard_zdf_hdf01a_1080i25_8_track_xdcam_hd422_v1_2_v1.yaml | 13 | 10 |
| 3 | - ARD_ZDF_HDF01b 1080i25 16 Track XDCAM HD422 V1.2 | imported: presets/library/vidchecker/vc003_ard_zdf_hdf01b_1080i25_16_track_xdcam_hd422_v1_2_v1.yaml | 13 | 10 |
| 4 | - ARD_ZDF_HDF02a 1080i25 8 Track AVC-I V1.2 | imported: presets/library/vidchecker/vc004_ard_zdf_hdf02a_1080i25_8_track_avc_i_v1_2_v1.yaml | 12 | 11 |
| 5 | - ARD_ZDF_HDF02b 1080i25 16 Track AVC-I V1.2 | imported: presets/library/vidchecker/vc005_ard_zdf_hdf02b_1080i25_16_track_avc_i_v1_2_v1.yaml | 12 | 11 |
| 6 | - ARD_ZDF_HDF03a 720p50 8 Track AVC-I V1.2 | imported: presets/library/vidchecker/vc006_ard_zdf_hdf03a_720p50_8_track_avc_i_v1_2_v1.yaml | 12 | 11 |
| 7 | - ARD_ZDF_HDF03b 720p50 16 Track AVC-I V1.2 | imported: presets/library/vidchecker/vc007_ard_zdf_hdf03b_720p50_16_track_avc_i_v1_2_v1.yaml | 12 | 11 |
| 8 | - ARD_ZDF_SDF01 576i25 1 Track D10 IMX50 V1.0 | imported: presets/library/vidchecker/vc008_ard_zdf_sdf01_576i25_1_track_d10_imx50_v1_0_v1.yaml | 13 | 8 |
| 9 | - ARD_ZDF_SDF02 576i25 8 Track DV-BASED 50 V1.0 | imported: presets/library/vidchecker/vc009_ard_zdf_sdf02_576i25_8_track_dv_based_50_v1_0_v1.yaml | 13 | 8 |
| 10 | - AS-10 50Mbps 1080i50 HIGH_HD_2014 | imported: presets/library/vidchecker/vc010_as_10_50mbps_1080i50_high_hd_2014_v1.yaml | 7 | 10 |
| 11 | - AS-10 50Mbps 1080p25 HIGH_HD_2014 | imported: presets/library/vidchecker/vc011_as_10_50mbps_1080p25_high_hd_2014_v1.yaml | 7 | 10 |
| 12 | - AS-11 UK DPP V4.3 HD AVC-I 16 Track Single Part | imported: presets/library/vidchecker/vc012_as_11_uk_dpp_v4_3_hd_avc_i_16_track_single_part_v1.yaml | 31 | 22 |
| 13 | - AS-11 UK DPP V4.3 HD AVC-I 4 Track Single Part | imported: presets/library/vidchecker/vc013_as_11_uk_dpp_v4_3_hd_avc_i_4_track_single_part_v1.yaml | 20 | 20 |
| 14 | - AS-11 UK DPP V4.3 SD IMX Single Part | imported: presets/library/vidchecker/vc014_as_11_uk_dpp_v4_3_sd_imx_single_part_v1.yaml | 19 | 17 |
| 19 | - AS-11 X1 UK DPP UHD | imported: presets/library/vidchecker/vc019_as_11_x1_uk_dpp_uhd_v1.yaml | 2 | 2 |
| 20 | - Chroma 75% color bars | skipped: no translatable checks | 0 | 1 |
| 21 | - DDV2 NPO MXF IMX-D10 v0.93 | imported: presets/library/vidchecker/vc021_ddv2_npo_mxf_imx_d10_v0_93_v1.yaml | 46 | 11 |
| 22 | - DDV2 NPO MXF XDCAM HD422 v0.94 | imported: presets/library/vidchecker/vc022_ddv2_npo_mxf_xdcam_hd422_v0_94_v1.yaml | 27 | 12 |
| 23 | - IMX NTSC | imported: presets/library/vidchecker/vc023_imx_ntsc_v1.yaml | 5 | 7 |
| 24 | - Loudness ATSC correct | imported: presets/library/vidchecker/vc024_loudness_atsc_correct_v1.yaml | 2 | 0 |
| 25 | - Loudness EBU correct | imported: presets/library/vidchecker/vc025_loudness_ebu_correct_v1.yaml | 2 | 0 |
| 26 | - Loudness EBU r128s1 Momentary | imported: presets/library/vidchecker/vc026_loudness_ebu_r128s1_momentary_v1.yaml | 3 | 0 |
| 27 | - Loudness EBU r128s1 Short-term | imported: presets/library/vidchecker/vc027_loudness_ebu_r128s1_short_term_v1.yaml | 3 | 0 |
| 28 | - MPEG2 SD NTSC | imported: presets/library/vidchecker/vc028_mpeg2_sd_ntsc_v1.yaml | 4 | 1 |
| 29 | - MPEG2 SD PAL | imported: presets/library/vidchecker/vc029_mpeg2_sd_pal_v1.yaml | 4 | 1 |
| 30 | - MXF AVC-I 100 | imported: presets/library/vidchecker/vc030_mxf_avc_i_100_v1.yaml | 5 | 7 |
| 31 | - MXF IMX50 Levels | imported: presets/library/vidchecker/vc031_mxf_imx50_levels_v1.yaml | 4 | 6 |
| 37 | - ProRes HQ HD | imported: presets/library/vidchecker/vc037_prores_hq_hd_v1.yaml | 5 | 7 |
| 39 | - Video Levels re-encode | skipped: no translatable checks | 0 | 3 |
| 40 | - XDCAM HD | imported: presets/library/vidchecker/vc040_xdcam_hd_v1.yaml | 3 | 5 |
| 41 | - XDCAM HD422 | imported: presets/library/vidchecker/vc041_xdcam_hd422_v1.yaml | 5 | 7 |
| 42 | - AS-11 X9 NABA DPP HD, PCM audio (work in progress) | imported: presets/library/vidchecker/vc042_as_11_x9_naba_dpp_hd_pcm_audio_work_in_progress_v1.yaml | 1 | 2 |
| 43 | - AS-11 UK DPP V5.0 HD AVC-I 16 Track Single Part | imported: presets/library/vidchecker/vc043_as_11_uk_dpp_v5_0_hd_avc_i_16_track_single_part_v1.yaml | 31 | 20 |
| 44 | - AS-11 UK DPP V5.0 HD AVC-I 4 Track Single Part | imported: presets/library/vidchecker/vc044_as_11_uk_dpp_v5_0_hd_avc_i_4_track_single_part_v1.yaml | 20 | 18 |
| 45 | - AS-11 UK DPP V5.0 SD IMX Single Part | imported: presets/library/vidchecker/vc045_as_11_uk_dpp_v5_0_sd_imx_single_part_v1.yaml | 19 | 15 |
| 46 | - Amazon v5.0 - ProRes422HQ MOV - 8Ch | imported: presets/library/vidchecker/vc046_amazon_v5_0_prores422hq_mov_8ch_v1.yaml | 48 | 7 |
| 47 | - iTunes HD TV - ProRes 1080i2997 | imported: presets/library/vidchecker/vc047_itunes_hd_tv_prores_1080i2997_v1.yaml | 5 | 8 |
| 48 | - iTunes HD TV - ProRes 1080p2398 v5.2.8 | imported: presets/library/vidchecker/vc048_itunes_hd_tv_prores_1080p2398_v5_2_8_v1.yaml | 5 | 8 |
| 49 | - iTunes HD TV - ProRes 1080p25 v5.2.8 | imported: presets/library/vidchecker/vc049_itunes_hd_tv_prores_1080p25_v5_2_8_v1.yaml | 5 | 8 |
| 50 | - iTunes HD TV - ProRes 1080p2997 | imported: presets/library/vidchecker/vc050_itunes_hd_tv_prores_1080p2997_v1.yaml | 5 | 8 |
| 73 | - PBS - XDCAM 422 1080i 29.97 - 8 Track Stereo Program | imported: presets/library/vidchecker/vc073_pbs_xdcam_422_1080i_29_97_8_track_stereo_program_v1.yaml | 21 | 20 |
| 76 | - PBS - XDCAM 422 1080i 29.97 - 8 Track Surround Program | imported: presets/library/vidchecker/vc076_pbs_xdcam_422_1080i_29_97_8_track_surround_program_v1.yaml | 21 | 20 |
| 77 | - PBS - DNxHD 1080i 29.97 - 8 Track Stereo Program | imported: presets/library/vidchecker/vc077_pbs_dnxhd_1080i_29_97_8_track_stereo_program_v1.yaml | 20 | 21 |
| 78 | - PBS - DNxHD 1080i 29.97 - 8 Track Surround Program | imported: presets/library/vidchecker/vc078_pbs_dnxhd_1080i_29_97_8_track_surround_program_v1.yaml | 20 | 21 |
| 88 | - Netflix - Licensed Content v9.0 - HD ProResHQ - 2Ch Audio | imported: presets/library/vidchecker/vc088_netflix_licensed_content_v9_0_hd_proreshq_2ch_audio_v1.yaml | 13 | 16 |
| 104 | - Netflix - Licensed Content v9.0 - HD IMF (Photon)  - 2Ch Audio | imported: presets/library/vidchecker/vc104_netflix_licensed_content_v9_0_hd_imf_photon_2ch_audio_v1.yaml | 14 | 12 |
| 105 | - Netflix - Licensed Content v9.0 - SD ProResHQ - 2Ch Audio | imported: presets/library/vidchecker/vc105_netflix_licensed_content_v9_0_sd_proreshq_2ch_audio_v1.yaml | 13 | 16 |
| 106 | - Netflix - Licensed Content v9.0 - 2K IMF (Photon)  - 2Ch Audio | imported: presets/library/vidchecker/vc106_netflix_licensed_content_v9_0_2k_imf_photon_2ch_audio_v1.yaml | 14 | 12 |
| 107 | - Netflix - Licensed Content v9.0 - 4k (UHD) ProResHQ - 2Ch Audio | imported: presets/library/vidchecker/vc107_netflix_licensed_content_v9_0_4k_uhd_proreshq_2ch_audio_v1.yaml | 13 | 16 |
| 108 | - Netflix - Licensed Content v9.0 - 4K (UHD) IMF (Photon)  - 2Ch Audio | imported: presets/library/vidchecker/vc108_netflix_licensed_content_v9_0_4k_uhd_imf_photon_2ch_audio_v1.yaml | 14 | 12 |
| 109 | - Netflix - Licensed Content v9.0 - 2K ProResHQ - 2Ch Audio | imported: presets/library/vidchecker/vc109_netflix_licensed_content_v9_0_2k_proreshq_2ch_audio_v1.yaml | 13 | 16 |
| 110 | TOPIC-Delivery | imported: presets/clients/topic/delivery_v1.yaml | 11 | 3 |
| 111 | New Template | skipped: no translatable checks | 0 | 0 |
| 112 | Audio-Stereo-Test | imported: presets/clients/deepdub-internal/audio_stereo_test_v1.yaml | 4 | 2 |
| 113 | Vanda-51-Audio | imported: presets/clients/vanda/51_audio_v1.yaml | 5 | 0 |
| 114 | Vanda-20-Audio | imported: presets/clients/vanda/20_audio_v1.yaml | 6 | 1 |
| 115 | Deliver-Audio | hand-translated: presets/clients/marimba/deliver_audio_v1.yaml | 0 | 0 |
| 116 | Delivery | hand-translated: presets/clients/marimba/delivery_v1.yaml | 0 | 0 |
| 117 | Delivery-51-Audio | imported: presets/clients/marimba/delivery_51_audio_v1.yaml | 5 | 0 |
