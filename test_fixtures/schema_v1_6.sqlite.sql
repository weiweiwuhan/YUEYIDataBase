-- AOI Industrial Asset Catalog | 27 tables

-- Non-destructive DDL: existing tables are preserved.

CREATE TABLE IF NOT EXISTS `storage_locations` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `root_path` TEXT NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  UNIQUE (`name`)
);

CREATE TABLE IF NOT EXISTS `product_categories` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `parent_id` INTEGER,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`parent_id`) REFERENCES `product_categories` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`name`)
);

CREATE TABLE IF NOT EXISTS `materials` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  UNIQUE (`name`)
);

CREATE TABLE IF NOT EXISTS `process_types` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  UNIQUE (`name`)
);

CREATE TABLE IF NOT EXISTS `defect_types` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  UNIQUE (`name`)
);

CREATE TABLE IF NOT EXISTS `projects` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `code` TEXT NOT NULL,
  `name` TEXT NOT NULL,
  `customer_name` TEXT,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  UNIQUE (`code`)
);

CREATE TABLE IF NOT EXISTS `products` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `code` TEXT,
  `name` TEXT NOT NULL,
  `category_id` INTEGER,
  `material_id` INTEGER,
  `spec_text` TEXT,
  `diameter_mm` REAL,
  `length_mm` REAL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`category_id`) REFERENCES `product_categories` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`material_id`) REFERENCES `materials` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`diameter_mm` IS NULL OR `diameter_mm` >= 0),
  CHECK (`length_mm` IS NULL OR `length_mm` >= 0),
  UNIQUE (`code`)
);

CREATE TABLE IF NOT EXISTS `assets` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `asset_type` TEXT NOT NULL,
  `file_name` TEXT NOT NULL,
  `storage_location_id` INTEGER,
  `relative_path` TEXT,
  `storage_mode` TEXT NOT NULL,
  `file_size` INTEGER,
  `sha256` TEXT,
  `status` TEXT NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  CHECK (`asset_type` IN ('image', 'archive', 'engineering', 'annotation', 'document', 'other')),
  FOREIGN KEY (`storage_location_id`) REFERENCES `storage_locations` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`storage_mode` IN ('file', 'archive_member')),
  CHECK (`file_size` IS NULL OR `file_size` >= 0),
  CHECK (`status` IN ('available', 'unverified', 'missing', 'pending', 'failed'))
);

CREATE TABLE IF NOT EXISTS `images` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `asset_id` INTEGER NOT NULL,
  `width` INTEGER,
  `height` INTEGER,
  `channels` INTEGER,
  `quality_label` TEXT NOT NULL,
  `inspection_surface` TEXT,
  `station_name` TEXT,
  `annotation_status` TEXT NOT NULL,
  `thumbnail_path` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`width` IS NULL OR `width` >= 0),
  CHECK (`height` IS NULL OR `height` >= 0),
  CHECK (`channels` IS NULL OR `channels` >= 0),
  CHECK (`quality_label` IN ('unknown', 'OK', 'NG')),
  CHECK (`annotation_status` IN ('unlabeled', 'labeled', 'reviewed')),
  UNIQUE (`asset_id`)
);

CREATE TABLE IF NOT EXISTS `engineering_projects` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `asset_id` INTEGER NOT NULL,
  `local_path` TEXT,
  `name` TEXT NOT NULL,
  `image_count` INTEGER,
  `software_name` TEXT,
  `software_version` TEXT,
  `engineering_version` TEXT,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`image_count` IS NULL OR `image_count` >= 0),
  UNIQUE (`asset_id`)
);

CREATE TABLE IF NOT EXISTS `project_products` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `project_id` INTEGER NOT NULL,
  `product_id` INTEGER NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`project_id`, `product_id`)
);

CREATE TABLE IF NOT EXISTS `project_assets` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `project_id` INTEGER NOT NULL,
  `asset_id` INTEGER NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`project_id`, `asset_id`)
);

CREATE TABLE IF NOT EXISTS `asset_products` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `asset_id` INTEGER NOT NULL,
  `product_id` INTEGER NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`asset_id`, `product_id`)
);

CREATE TABLE IF NOT EXISTS `product_processes` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `product_id` INTEGER NOT NULL,
  `process_id` INTEGER NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`process_id`) REFERENCES `process_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`product_id`, `process_id`)
);

CREATE TABLE IF NOT EXISTS `image_defects` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `image_id` INTEGER NOT NULL,
  `defect_type_id` INTEGER NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`defect_type_id`) REFERENCES `defect_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`image_id`, `defect_type_id`)
);

CREATE TABLE IF NOT EXISTS `asset_defects` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `asset_id` INTEGER NOT NULL,
  `defect_type_id` INTEGER NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`defect_type_id`) REFERENCES `defect_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`asset_id`, `defect_type_id`)
);

CREATE TABLE IF NOT EXISTS `asset_relations` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `source_asset_id` INTEGER NOT NULL,
  `target_asset_id` INTEGER NOT NULL,
  `relation_type` TEXT NOT NULL,
  `member_path` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`source_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`target_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`relation_type` IN ('contains', 'paired', 'annotation', 'version')),
  UNIQUE (`source_asset_id`, `target_asset_id`, `relation_type`)
);

CREATE TABLE IF NOT EXISTS `image_embeddings` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `image_id` INTEGER NOT NULL,
  `model_name` TEXT NOT NULL,
  `model_version` TEXT NOT NULL,
  `dimension` INTEGER NOT NULL,
  `vector_key` TEXT NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`dimension` IS NULL OR `dimension` >= 0),
  UNIQUE (`image_id`, `model_name`, `model_version`),
  UNIQUE (`vector_key`)
);

CREATE TABLE IF NOT EXISTS `videos` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `image_id` INTEGER,
  `project_id` INTEGER,
  `name` TEXT NOT NULL,
  `file_name` TEXT NOT NULL,
  `relative_path` TEXT NOT NULL,
  `file_size` INTEGER,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`file_size` IS NULL OR `file_size` >= 0)
);

CREATE TABLE IF NOT EXISTS `technical_agreements` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `project_id` INTEGER NOT NULL,
  `document_type` TEXT,
  `code` TEXT NOT NULL,
  `name` TEXT NOT NULL,
  `signed_date` TEXT,
  `requirements` TEXT,
  `extracted_text` TEXT,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`code`)
);

CREATE TABLE IF NOT EXISTS `agreement_products` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `agreement_id` INTEGER NOT NULL,
  `product_id` INTEGER NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`agreement_id`) REFERENCES `technical_agreements` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`agreement_id`, `product_id`)
);

CREATE TABLE IF NOT EXISTS `after_sales` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `project_id` INTEGER NOT NULL,
  `product_id` INTEGER NOT NULL,
  `name` TEXT NOT NULL,
  `service_date` TEXT,
  `status` TEXT NOT NULL,
  `symptom` TEXT,
  `cause` TEXT,
  `resolution` TEXT,
  `experience` TEXT,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`status` IN ('待处理', '处理中', '已解决'))
);

CREATE TABLE IF NOT EXISTS `agreement_files` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `agreement_id` INTEGER NOT NULL,
  `asset_id` INTEGER NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`agreement_id`) REFERENCES `technical_agreements` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`asset_id`)
);

CREATE TABLE IF NOT EXISTS `model_tests` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `test_module` TEXT,
  `test_method` TEXT,
  `expected_result` TEXT,
  `actual_result` TEXT,
  `project_id` INTEGER,
  `model_name` TEXT NOT NULL,
  `model_version` TEXT,
  `test_date` TEXT,
  `result` TEXT,
  `prompt` TEXT,
  `product_id` INTEGER,
  `test_count` INTEGER,
  `detection_rate` REAL,
  `miss_rate` REAL,
  `yield_rate` REAL,
  `light_source` TEXT,
  `camera` TEXT,
  `lens` TEXT,
  `working_distance_mm` REAL,
  `product_spec` TEXT,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`result` IN ('待评价', '效果好', '一般', '效果差')),
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`test_count` IS NULL OR `test_count` >= 0),
  CHECK (`detection_rate` IS NULL OR `detection_rate` <= 100),
  CHECK (`detection_rate` IS NULL OR `detection_rate` >= 0),
  CHECK (`miss_rate` IS NULL OR `miss_rate` <= 100),
  CHECK (`miss_rate` IS NULL OR `miss_rate` >= 0),
  CHECK (`yield_rate` IS NULL OR `yield_rate` <= 100),
  CHECK (`yield_rate` IS NULL OR `yield_rate` >= 0),
  CHECK (`working_distance_mm` IS NULL OR `working_distance_mm` >= 0)
);

CREATE TABLE IF NOT EXISTS `model_test_files` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `test_id` INTEGER NOT NULL,
  `asset_id` INTEGER NOT NULL,
  `role` TEXT NOT NULL,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`test_id`) REFERENCES `model_tests` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`role` IN ('input', 'result')),
  UNIQUE (`asset_id`)
);

CREATE TABLE IF NOT EXISTS `technical_experiences` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` TEXT NOT NULL,
  `category` TEXT,
  `tags` TEXT,
  `content` TEXT NOT NULL,
  `remark` TEXT,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT
);

CREATE TABLE IF NOT EXISTS `technical_experience_files` (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `experience_id` INTEGER NOT NULL,
  `asset_id` INTEGER,
  `video_id` INTEGER,
  `created_by` TEXT,
  `created_at` TEXT,
  `updated_by` TEXT,
  `updated_at` TEXT,
  FOREIGN KEY (`experience_id`) REFERENCES `technical_experiences` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`video_id`) REFERENCES `videos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`experience_id`, `asset_id`),
  UNIQUE (`experience_id`, `video_id`)
);

CREATE INDEX IF NOT EXISTS `idx_product_categories_parent_id` ON `product_categories` (`parent_id`);

CREATE INDEX IF NOT EXISTS `idx_products_category_id` ON `products` (`category_id`);

CREATE INDEX IF NOT EXISTS `idx_products_material_id` ON `products` (`material_id`);

CREATE INDEX IF NOT EXISTS `idx_assets_storage_location_id` ON `assets` (`storage_location_id`);

CREATE INDEX IF NOT EXISTS `idx_images_asset_id` ON `images` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_engineering_projects_asset_id` ON `engineering_projects` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_project_products_project_id` ON `project_products` (`project_id`);

CREATE INDEX IF NOT EXISTS `idx_project_products_product_id` ON `project_products` (`product_id`);

CREATE INDEX IF NOT EXISTS `idx_project_assets_project_id` ON `project_assets` (`project_id`);

CREATE INDEX IF NOT EXISTS `idx_project_assets_asset_id` ON `project_assets` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_asset_products_asset_id` ON `asset_products` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_asset_products_product_id` ON `asset_products` (`product_id`);

CREATE INDEX IF NOT EXISTS `idx_product_processes_product_id` ON `product_processes` (`product_id`);

CREATE INDEX IF NOT EXISTS `idx_product_processes_process_id` ON `product_processes` (`process_id`);

CREATE INDEX IF NOT EXISTS `idx_image_defects_image_id` ON `image_defects` (`image_id`);

CREATE INDEX IF NOT EXISTS `idx_image_defects_defect_type_id` ON `image_defects` (`defect_type_id`);

CREATE INDEX IF NOT EXISTS `idx_asset_defects_asset_id` ON `asset_defects` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_asset_defects_defect_type_id` ON `asset_defects` (`defect_type_id`);

CREATE INDEX IF NOT EXISTS `idx_asset_relations_source_asset_id` ON `asset_relations` (`source_asset_id`);

CREATE INDEX IF NOT EXISTS `idx_asset_relations_target_asset_id` ON `asset_relations` (`target_asset_id`);

CREATE INDEX IF NOT EXISTS `idx_image_embeddings_image_id` ON `image_embeddings` (`image_id`);

CREATE INDEX IF NOT EXISTS `idx_videos_image_id` ON `videos` (`image_id`);

CREATE INDEX IF NOT EXISTS `idx_videos_project_id` ON `videos` (`project_id`);

CREATE INDEX IF NOT EXISTS `idx_technical_agreements_project_id` ON `technical_agreements` (`project_id`);

CREATE INDEX IF NOT EXISTS `idx_agreement_products_agreement_id` ON `agreement_products` (`agreement_id`);

CREATE INDEX IF NOT EXISTS `idx_agreement_products_product_id` ON `agreement_products` (`product_id`);

CREATE INDEX IF NOT EXISTS `idx_after_sales_project_id` ON `after_sales` (`project_id`);

CREATE INDEX IF NOT EXISTS `idx_after_sales_product_id` ON `after_sales` (`product_id`);

CREATE INDEX IF NOT EXISTS `idx_agreement_files_agreement_id` ON `agreement_files` (`agreement_id`);

CREATE INDEX IF NOT EXISTS `idx_agreement_files_asset_id` ON `agreement_files` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_model_tests_project_id` ON `model_tests` (`project_id`);

CREATE INDEX IF NOT EXISTS `idx_model_tests_product_id` ON `model_tests` (`product_id`);

CREATE INDEX IF NOT EXISTS `idx_model_test_files_test_id` ON `model_test_files` (`test_id`);

CREATE INDEX IF NOT EXISTS `idx_model_test_files_asset_id` ON `model_test_files` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_technical_experience_files_experience_id` ON `technical_experience_files` (`experience_id`);

CREATE INDEX IF NOT EXISTS `idx_technical_experience_files_asset_id` ON `technical_experience_files` (`asset_id`);

CREATE INDEX IF NOT EXISTS `idx_technical_experience_files_video_id` ON `technical_experience_files` (`video_id`);
