-- AOI Industrial Asset Catalog | 31 tables

-- Non-destructive DDL: existing tables are preserved.

CREATE DATABASE IF NOT EXISTS aoi_catalog CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE aoi_catalog;

CREATE TABLE IF NOT EXISTS `storage_locations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `root_path` VARCHAR(1024) NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `product_categories` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `parent_id` BIGINT,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`parent_id`) REFERENCES `product_categories` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`parent_id` IS NULL OR `parent_id` >= 0),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `materials` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `process_types` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `defect_types` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `projects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(191) NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `customer_name` VARCHAR(191),
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  UNIQUE (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(191),
  `name` VARCHAR(191) NOT NULL,
  `category_id` BIGINT,
  `material_id` BIGINT,
  `spec_text` VARCHAR(191),
  `diameter_mm` DOUBLE,
  `length_mm` DOUBLE,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`category_id`) REFERENCES `product_categories` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`category_id` IS NULL OR `category_id` >= 0),
  FOREIGN KEY (`material_id`) REFERENCES `materials` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`material_id` IS NULL OR `material_id` >= 0),
  CHECK (`diameter_mm` IS NULL OR `diameter_mm` >= 0),
  CHECK (`length_mm` IS NULL OR `length_mm` >= 0),
  UNIQUE (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `assets` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_type` VARCHAR(191) NOT NULL,
  `preview_asset_id` BIGINT,
  `file_name` VARCHAR(191) NOT NULL,
  `storage_location_id` BIGINT,
  `relative_path` VARCHAR(1024),
  `storage_mode` VARCHAR(191) NOT NULL,
  `file_size` BIGINT,
  `sha256` VARCHAR(191),
  `status` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  CHECK (`asset_type` IN ('image', 'archive', 'engineering', 'annotation', 'document', 'other')),
  FOREIGN KEY (`preview_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`preview_asset_id` IS NULL OR `preview_asset_id` >= 0),
  FOREIGN KEY (`storage_location_id`) REFERENCES `storage_locations` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`storage_location_id` IS NULL OR `storage_location_id` >= 0),
  CHECK (`storage_mode` IN ('file', 'archive_member')),
  CHECK (`file_size` IS NULL OR `file_size` >= 0),
  CHECK (`status` IN ('available', 'unverified', 'missing', 'pending', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `images` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_id` BIGINT NOT NULL,
  `width` BIGINT,
  `height` BIGINT,
  `channels` BIGINT,
  `quality_label` VARCHAR(191) NOT NULL,
  `inspection_surface` VARCHAR(191),
  `station_name` VARCHAR(191),
  `annotation_status` VARCHAR(191) NOT NULL,
  `thumbnail_path` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  CHECK (`width` IS NULL OR `width` >= 0),
  CHECK (`height` IS NULL OR `height` >= 0),
  CHECK (`channels` IS NULL OR `channels` >= 0),
  CHECK (`quality_label` IN ('unknown', 'OK', 'NG')),
  CHECK (`annotation_status` IN ('unlabeled', 'labeled', 'reviewed')),
  UNIQUE (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `engineering_projects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_id` BIGINT NOT NULL,
  `local_path` VARCHAR(1024),
  `name` VARCHAR(191) NOT NULL,
  `image_count` BIGINT,
  `software_name` VARCHAR(191),
  `software_version` VARCHAR(191),
  `engineering_version` VARCHAR(191),
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  CHECK (`image_count` IS NULL OR `image_count` >= 0),
  UNIQUE (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `project_products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`project_id` IS NULL OR `project_id` >= 0),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`product_id` IS NULL OR `product_id` >= 0),
  UNIQUE (`project_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `project_assets` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `asset_id` BIGINT NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`project_id` IS NULL OR `project_id` >= 0),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  UNIQUE (`project_id`, `asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `asset_products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`product_id` IS NULL OR `product_id` >= 0),
  UNIQUE (`asset_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `product_processes` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `product_id` BIGINT NOT NULL,
  `process_id` BIGINT NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`product_id` IS NULL OR `product_id` >= 0),
  FOREIGN KEY (`process_id`) REFERENCES `process_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`process_id` IS NULL OR `process_id` >= 0),
  UNIQUE (`product_id`, `process_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `image_defects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `image_id` BIGINT NOT NULL,
  `defect_type_id` BIGINT NOT NULL,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`image_id` IS NULL OR `image_id` >= 0),
  FOREIGN KEY (`defect_type_id`) REFERENCES `defect_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`defect_type_id` IS NULL OR `defect_type_id` >= 0),
  UNIQUE (`image_id`, `defect_type_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `asset_defects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_id` BIGINT NOT NULL,
  `defect_type_id` BIGINT NOT NULL,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  FOREIGN KEY (`defect_type_id`) REFERENCES `defect_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`defect_type_id` IS NULL OR `defect_type_id` >= 0),
  UNIQUE (`asset_id`, `defect_type_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `asset_relations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `source_asset_id` BIGINT NOT NULL,
  `target_asset_id` BIGINT NOT NULL,
  `relation_type` VARCHAR(191) NOT NULL,
  `member_path` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`source_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`source_asset_id` IS NULL OR `source_asset_id` >= 0),
  FOREIGN KEY (`target_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`target_asset_id` IS NULL OR `target_asset_id` >= 0),
  CHECK (`relation_type` IN ('contains', 'paired', 'annotation', 'version')),
  UNIQUE (`source_asset_id`, `target_asset_id`, `relation_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `image_embeddings` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `image_id` BIGINT NOT NULL,
  `model_name` VARCHAR(191) NOT NULL,
  `model_version` VARCHAR(191) NOT NULL,
  `dimension` BIGINT NOT NULL,
  `vector_key` VARCHAR(191) NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`image_id` IS NULL OR `image_id` >= 0),
  CHECK (`dimension` IS NULL OR `dimension` >= 0),
  UNIQUE (`image_id`, `model_name`, `model_version`),
  UNIQUE (`vector_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `videos` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `image_id` BIGINT,
  `project_id` BIGINT,
  `asset_id` BIGINT,
  `preview_asset_id` BIGINT,
  `name` VARCHAR(191) NOT NULL,
  `file_name` VARCHAR(191) NOT NULL,
  `relative_path` VARCHAR(1024) NOT NULL,
  `file_size` BIGINT,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`image_id` IS NULL OR `image_id` >= 0),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`project_id` IS NULL OR `project_id` >= 0),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  FOREIGN KEY (`preview_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`preview_asset_id` IS NULL OR `preview_asset_id` >= 0),
  CHECK (`file_size` IS NULL OR `file_size` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `technical_agreements` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT,
  `document_type` VARCHAR(191),
  `code` VARCHAR(191) NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `signed_date` VARCHAR(191),
  `requirements` VARCHAR(1024),
  `extracted_text` LONGTEXT,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`project_id` IS NULL OR `project_id` >= 0),
  UNIQUE (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agreement_products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `agreement_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`agreement_id`) REFERENCES `technical_agreements` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`agreement_id` IS NULL OR `agreement_id` >= 0),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`product_id` IS NULL OR `product_id` >= 0),
  UNIQUE (`agreement_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `after_sales` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `service_date` VARCHAR(191),
  `status` VARCHAR(191) NOT NULL,
  `symptom` MEDIUMTEXT,
  `cause` MEDIUMTEXT,
  `resolution` MEDIUMTEXT,
  `experience` MEDIUMTEXT,
  `remark` MEDIUMTEXT,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`project_id` IS NULL OR `project_id` >= 0),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`product_id` IS NULL OR `product_id` >= 0),
  CHECK (`status` IN ('待处理', '处理中', '已解决'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agreement_files` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `agreement_id` BIGINT NOT NULL,
  `asset_id` BIGINT NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`agreement_id`) REFERENCES `technical_agreements` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`agreement_id` IS NULL OR `agreement_id` >= 0),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  UNIQUE (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `model_tests` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `test_module` VARCHAR(191),
  `inspection_surface` VARCHAR(191),
  `acceptance_criteria` MEDIUMTEXT,
  `parameter_snapshot` MEDIUMTEXT,
  `confirmation_status` VARCHAR(191),
  `test_method` MEDIUMTEXT,
  `expected_result` MEDIUMTEXT,
  `actual_result` MEDIUMTEXT,
  `project_id` BIGINT,
  `model_name` VARCHAR(191) NOT NULL,
  `model_version` VARCHAR(191),
  `test_date` VARCHAR(191),
  `result` VARCHAR(191),
  `prompt` VARCHAR(1024),
  `product_id` BIGINT,
  `test_count` BIGINT,
  `detection_rate` DOUBLE,
  `miss_rate` DOUBLE,
  `yield_rate` DOUBLE,
  `light_source` VARCHAR(191),
  `camera` VARCHAR(191),
  `lens` VARCHAR(191),
  `working_distance_mm` DOUBLE,
  `product_spec` VARCHAR(1024),
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  CHECK (`confirmation_status` IN ('待补充', '待验证', '经验建议', '已验证')),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`project_id` IS NULL OR `project_id` >= 0),
  CHECK (`result` IN ('待评价', '效果好', '一般', '效果差')),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`product_id` IS NULL OR `product_id` >= 0),
  CHECK (`test_count` IS NULL OR `test_count` >= 0),
  CHECK (`detection_rate` IS NULL OR `detection_rate` <= 100),
  CHECK (`detection_rate` IS NULL OR `detection_rate` >= 0),
  CHECK (`miss_rate` IS NULL OR `miss_rate` <= 100),
  CHECK (`miss_rate` IS NULL OR `miss_rate` >= 0),
  CHECK (`yield_rate` IS NULL OR `yield_rate` <= 100),
  CHECK (`yield_rate` IS NULL OR `yield_rate` >= 0),
  CHECK (`working_distance_mm` IS NULL OR `working_distance_mm` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `model_test_files` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `test_id` BIGINT NOT NULL,
  `asset_id` BIGINT NOT NULL,
  `role` VARCHAR(191) NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`test_id`) REFERENCES `model_tests` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`test_id` IS NULL OR `test_id` >= 0),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  CHECK (`role` IN ('input', 'result')),
  UNIQUE (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `technical_experiences` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `experience_type` VARCHAR(191),
  `conditions` MEDIUMTEXT,
  `confirmation_status` VARCHAR(191),
  `category` VARCHAR(191),
  `tags` VARCHAR(191),
  `content` MEDIUMTEXT NOT NULL,
  `remark` MEDIUMTEXT,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  CHECK (`experience_type` IN ('标注规范', '调试经验', '原理解释', '工具操作', '其他')),
  CHECK (`confirmation_status` IN ('待补充', '待验证', '经验建议', '已验证'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `technical_experience_files` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `experience_id` BIGINT NOT NULL,
  `asset_id` BIGINT,
  `video_id` BIGINT,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  FOREIGN KEY (`experience_id`) REFERENCES `technical_experiences` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`experience_id` IS NULL OR `experience_id` >= 0),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`asset_id` IS NULL OR `asset_id` >= 0),
  FOREIGN KEY (`video_id`) REFERENCES `videos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`video_id` IS NULL OR `video_id` >= 0),
  UNIQUE (`experience_id`, `asset_id`),
  UNIQUE (`experience_id`, `video_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `document_types` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `technical_objects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `object_kind` VARCHAR(191) NOT NULL,
  `version` VARCHAR(191),
  `specification` MEDIUMTEXT,
  `remark` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  CHECK (`object_kind` IN ('相机', '镜头', '光源', '工具', '软件', '模型', '其他')),
  UNIQUE (`name`, `object_kind`, `version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `entity_aliases` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `entity_table` VARCHAR(191) NOT NULL,
  `entity_id` BIGINT NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  CHECK (`entity_id` IS NULL OR `entity_id` >= 0),
  UNIQUE (`entity_table`, `entity_id`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `knowledge_links` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `source_table` VARCHAR(191) NOT NULL,
  `source_id` BIGINT NOT NULL,
  `relation` VARCHAR(191) NOT NULL,
  `target_table` VARCHAR(191) NOT NULL,
  `target_id` BIGINT NOT NULL,
  `conditions` MEDIUMTEXT,
  `confirmation_status` VARCHAR(191),
  `evidence_test_id` BIGINT,
  `evidence_document_id` BIGINT,
  `evidence_locator` VARCHAR(1024),
  `created_by` VARCHAR(191),
  `created_at` VARCHAR(191),
  `updated_by` VARCHAR(191),
  `updated_at` VARCHAR(191),
  CHECK (`source_id` IS NULL OR `source_id` >= 0),
  CHECK (`relation` IN ('适用于', '测试对象', '测试缺陷', '使用设备', '参考规范', '测试依据', '相关资料')),
  CHECK (`target_id` IS NULL OR `target_id` >= 0),
  CHECK (`confirmation_status` IN ('待补充', '待验证', '经验建议', '已验证')),
  FOREIGN KEY (`evidence_test_id`) REFERENCES `model_tests` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`evidence_test_id` IS NULL OR `evidence_test_id` >= 0),
  FOREIGN KEY (`evidence_document_id`) REFERENCES `technical_agreements` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`evidence_document_id` IS NULL OR `evidence_document_id` >= 0),
  UNIQUE (`source_table`, `source_id`, `relation`, `target_table`, `target_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
