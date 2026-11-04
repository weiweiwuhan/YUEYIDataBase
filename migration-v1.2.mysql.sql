-- Back up first. Run once on V1.1 databases only.
USE aoi_catalog;
ALTER TABLE engineering_projects ADD COLUMN local_path VARCHAR(1024) NULL;
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
