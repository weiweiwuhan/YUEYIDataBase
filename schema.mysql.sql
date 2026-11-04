-- AOI Industrial Asset Catalog | 22 tables

-- Non-destructive DDL: existing tables are preserved.

CREATE DATABASE IF NOT EXISTS aoi_catalog CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE aoi_catalog;

CREATE TABLE IF NOT EXISTS `storage_locations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `root_path` VARCHAR(1024) NOT NULL,
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `product_categories` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `parent_id` BIGINT,
  FOREIGN KEY (`parent_id`) REFERENCES `product_categories` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `materials` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `process_types` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `defect_types` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  UNIQUE (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `projects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(191) NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `customer_name` VARCHAR(191),
  `remark` VARCHAR(1024),
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
  FOREIGN KEY (`category_id`) REFERENCES `product_categories` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`material_id`) REFERENCES `materials` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`diameter_mm` IS NULL OR `diameter_mm` >= 0),
  CHECK (`length_mm` IS NULL OR `length_mm` >= 0),
  UNIQUE (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `assets` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_type` VARCHAR(191) NOT NULL,
  `file_name` VARCHAR(191) NOT NULL,
  `storage_location_id` BIGINT,
  `relative_path` VARCHAR(1024),
  `storage_mode` VARCHAR(191) NOT NULL,
  `file_size` BIGINT,
  `sha256` VARCHAR(191),
  `status` VARCHAR(191) NOT NULL,
  `remark` VARCHAR(1024),
  CHECK (`asset_type` IN ('image', 'archive', 'engineering', 'annotation', 'document', 'other')),
  FOREIGN KEY (`storage_location_id`) REFERENCES `storage_locations` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
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
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
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
  `software_name` VARCHAR(191),
  `software_version` VARCHAR(191),
  `engineering_version` VARCHAR(191),
  `remark` VARCHAR(1024),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `project_products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`project_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `project_assets` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `asset_id` BIGINT NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`project_id`, `asset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `asset_products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`asset_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `product_processes` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `product_id` BIGINT NOT NULL,
  `process_id` BIGINT NOT NULL,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`process_id`) REFERENCES `process_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`product_id`, `process_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `image_defects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `image_id` BIGINT NOT NULL,
  `defect_type_id` BIGINT NOT NULL,
  `remark` VARCHAR(1024),
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`defect_type_id`) REFERENCES `defect_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`image_id`, `defect_type_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `asset_defects` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `asset_id` BIGINT NOT NULL,
  `defect_type_id` BIGINT NOT NULL,
  `remark` VARCHAR(1024),
  FOREIGN KEY (`asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`defect_type_id`) REFERENCES `defect_types` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`asset_id`, `defect_type_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `asset_relations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `source_asset_id` BIGINT NOT NULL,
  `target_asset_id` BIGINT NOT NULL,
  `relation_type` VARCHAR(191) NOT NULL,
  `member_path` VARCHAR(1024),
  FOREIGN KEY (`source_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`target_asset_id`) REFERENCES `assets` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
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
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`dimension` IS NULL OR `dimension` >= 0),
  UNIQUE (`image_id`, `model_name`, `model_version`),
  UNIQUE (`vector_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `videos` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `image_id` BIGINT NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `file_name` VARCHAR(191) NOT NULL,
  `relative_path` VARCHAR(1024) NOT NULL,
  `file_size` BIGINT,
  `remark` VARCHAR(1024),
  FOREIGN KEY (`image_id`) REFERENCES `images` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`file_size` IS NULL OR `file_size` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `technical_agreements` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `code` VARCHAR(191) NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `signed_date` VARCHAR(191),
  `requirements` VARCHAR(1024),
  `remark` VARCHAR(1024),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agreement_products` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `agreement_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  FOREIGN KEY (`agreement_id`) REFERENCES `technical_agreements` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  UNIQUE (`agreement_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `after_sales` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `project_id` BIGINT NOT NULL,
  `product_id` BIGINT NOT NULL,
  `name` VARCHAR(191) NOT NULL,
  `service_date` VARCHAR(191),
  `status` VARCHAR(191) NOT NULL,
  `symptom` VARCHAR(1024),
  `cause` VARCHAR(1024),
  `resolution` VARCHAR(1024),
  `experience` VARCHAR(1024),
  `remark` VARCHAR(1024),
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CHECK (`status` IN ('待处理', '处理中', '已解决'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
