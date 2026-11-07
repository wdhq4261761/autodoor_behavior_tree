import cv2
import numpy as np
from PIL import Image
from typing import Tuple, Optional, List, Dict


class ImageProcessor:
    """图像处理器

    提供模板匹配、颜色检测和图像哈希识别功能。
    """

    # 模板哈希缓存：{(模板phash, hash_type): 模板哈希值}
    _template_hash_cache: Dict[str, str] = {}

    # 判「是否具备可定位结构」的边缘能量阈值。
    # 实测参考：纯色块 0.00，真实截图纯色区 1.28（压缩噪声所致），
    # 色块+边界 17.37，细腻纹理 38.00。取 3.0 可稳定区分。
    MIN_EDGE_ENERGY = 3.0

    @staticmethod
    def _edge_energy(gray: np.ndarray) -> float:
        """Sobel 梯度均值，衡量区域是否具备可供模板定位的结构。

        比标准差更可靠：截图里的纯色区域因压缩噪声 std 可达 5 以上，
        但边缘能量只有 1 左右，能正确判定为"无结构"。
        """
        if gray.dtype != np.uint8:
            gray = np.clip(gray, 0, 255).astype(np.uint8)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        return float(np.mean(np.abs(gx) + np.abs(gy)))

    @staticmethod
    def find_template(source: Image.Image, template: Image.Image,
                      threshold: float = 0.8,
                      method: str = "sqdiff") -> Tuple[bool, Optional[Tuple[int, int]], float]:
        """模板匹配

        默认使用 TM_SQDIFF_NORMED。不使用 TM_CCOEFF_NORMED 作为默认值的原因：
        后者的归一化相关系数为 cov(T,I)/(σ_T·σ_I)，当源图局部区域方差 σ_I 为 0
        （纯色块、纯白对话框、大面积留白）时会出现 0/0，OpenCV 将其置为 1.0，
        导致整张响应矩阵恒为 1.0、minMaxLoc 取到首个位置 (0,0)，最终返回
        (0+半宽, 0+半高) 的错误坐标且置信度满分 —— 静默失败且无法用阈值过滤。

        Args:
            source: 源图像
            template: 模板图像
            threshold: 匹配阈值（相似度，越大越严格，0~1）
            method: 匹配算法，"sqdiff"（默认，抗纯色假匹配）
                    或 "ccoeff"（兼容旧行为，模板为纯色时自动降级为 sqdiff）

        Returns:
            (是否找到, 中心位置, 最高置信度) 元组。源图小于模板时返回 (False, None, 0.0)
        """
        source_array = np.array(source)
        template_array = np.array(template)

        # 统一转 RGB 三通道
        if len(source_array.shape) == 2:
            source_array = cv2.cvtColor(source_array, cv2.COLOR_GRAY2RGB)
        elif source_array.shape[2] == 4:
            source_array = cv2.cvtColor(source_array, cv2.COLOR_RGBA2RGB)

        if len(template_array.shape) == 2:
            template_array = cv2.cvtColor(template_array, cv2.COLOR_GRAY2RGB)
        elif template_array.shape[2] == 4:
            template_array = cv2.cvtColor(template_array, cv2.COLOR_RGBA2RGB)

        # 校验尺寸：源图必须 >= 模板
        sh, sw = source_array.shape[:2]
        th, tw = template_array.shape[:2]
        if sh < th or sw < tw:
            return False, None, 0.0

        source_gray = cv2.cvtColor(source_array, cv2.COLOR_RGB2GRAY)
        template_gray = cv2.cvtColor(template_array, cv2.COLOR_RGB2GRAY)

        # CCOEFF 在纯色模板上无意义（σ_T=0 同样触发 0/0），强制降级
        use_method = method
        if use_method == "ccoeff" and float(np.std(template_gray)) < 1.0:
            use_method = "sqdiff"

        # CCOEFF 在纯色源区域会把响应矩阵塌缩为常数（≈1.0），结果不可信，
        # 检出退化后同样降级为 SQDIFF 重算；未退化时直接复用这次的响应矩阵
        ccoeff_result = None
        if use_method == "ccoeff":
            probe = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            if float(probe.max() - probe.min()) < 1e-5:
                use_method = "sqdiff"
            else:
                ccoeff_result = probe

        if use_method == "ccoeff":
            _, max_val, _, max_loc = cv2.minMaxLoc(ccoeff_result)
            confidence = float(max_val)
            best_loc = max_loc
        else:
            # 定位用 SQDIFF：数值稳定，不会在纯色区域出现 0/0 塌缩。
            result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_SQDIFF_NORMED)
            _, _, min_loc, _ = cv2.minMaxLoc(result)
            best_loc = min_loc

            # 评分用局部 Pearson 相关：SQDIFF 只反映灰度差，纯色画面可能因
            # 灰度恰好接近而拿到 0.90+ 的高分（实测纯青底可达 0.906），
            # 必须用结构相关性复核；Pearson 对线性亮度变化免疫，语义与
            # CCOEFF 一致，但不依赖全图归一化，因此不会塌缩。
            h, w = template_gray.shape
            bx, by = best_loc
            patch = source_gray[by:by + h, bx:bx + w]
            template_f = template_gray.astype(np.float64)

            # 先判「有没有可定位的结构」。std 不可靠：真实截图的纯色区域
            # 因压缩噪声 std 可达 5.14，却毫无边界；改用边缘能量，实测
            # 纯色区 1.28、色块边界 17.37，区分明显。
            if ImageProcessor._edge_energy(template_gray) < ImageProcessor.MIN_EDGE_ENERGY:
                # 模板本身无结构，模板匹配无法定位，交由颜色检测处理
                confidence = 0.0
            elif ImageProcessor._edge_energy(patch) < ImageProcessor.MIN_EDGE_ENERGY:
                # 源区域无结构，与有结构的模板不可能匹配
                confidence = 0.0
            else:
                corr = float(np.corrcoef(
                    patch.astype(np.float64).ravel(),
                    template_f.ravel(),
                )[0, 1])
                confidence = max(0.0, min(1.0, corr))

        if confidence >= threshold:
            h, w = template_gray.shape
            center_x = best_loc[0] + w // 2
            center_y = best_loc[1] + h // 2
            return True, (center_x, center_y), confidence

        return False, None, confidence

    # ------------------------------------------------------------------
    # 多尺度匹配
    # ------------------------------------------------------------------
    @staticmethod
    def build_scales(scale_range: Tuple[float, float] = (0.85, 1.15),
                     steps: int = 5) -> List[float]:
        """生成等比缩放序列，用于 DPI / 窗口尺寸变化时的模板适配。"""
        low, high = float(scale_range[0]), float(scale_range[1])
        if low <= 0 or high <= 0:
            raise ValueError("scale_range 必须为正数")
        if low > high:
            low, high = high, low
        if steps <= 1:
            return [1.0]

        span = (high - low) / (steps - 1)
        scales = [round(low + i * span, 4) for i in range(steps)]
        # 保证 1.0 在候选内，避免遗漏原始尺寸
        if not any(abs(s - 1.0) < 1e-6 for s in scales) and low <= 1.0 <= high:
            scales.append(1.0)
            scales.sort()
        return scales

    # ------------------------------------------------------------------
    # 粗定位精修（级联）
    # ------------------------------------------------------------------
    @staticmethod
    def refine_bbox(source: Image.Image, coarse_bbox, color: Tuple[int, int, int],
                    expand: float = 3.0, tolerance: int = 50,
                    min_pixels: int = 8) -> Optional[Tuple[int, int, int, int]]:
        """用颜色连通域把粗定位框精修为精确 bbox。

        VLM 的 grounding 精度实测只有 20~50 px，且置信度不可靠（会报 1.0
        却偏 50 px），不能直接用于裁剪或点击。正确做法是级联：

            粗框 ──外扩──► 区域 ──颜色连通域──► 精确 bbox

        外扩倍数很关键：必须保证目标完整落入区域内，否则目标被边界截断，
        中位数/外接框都会偏向保留侧。实测外扩 3 倍即可把误差从 20~50 px
        收敛到 0~1 px。

        Args:
            source: 源图像
            coarse_bbox: 粗定位框 (x1, y1, x2, y2)，图像内坐标
            color: 目标主色 (R, G, B)
            expand: 外扩倍数（相对粗框尺寸）
            tolerance: 颜色容差
            min_pixels: 最小连通域面积

        Returns:
            精确 bbox (x1, y1, x2, y2)，失败返回 None
        """
        if not coarse_bbox or len(coarse_bbox) != 4:
            return None
        try:
            x1, y1, x2, y2 = (int(v) for v in coarse_bbox)
        except (TypeError, ValueError):
            return None

        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        half_w = max(1.0, (x2 - x1) * expand / 2.0)
        half_h = max(1.0, (y2 - y1) * expand / 2.0)

        rx1 = max(0, int(cx - half_w))
        ry1 = max(0, int(cy - half_h))
        rx2 = min(source.width, int(cx + half_w))
        ry2 = min(source.height, int(cy + half_h))
        if rx2 <= rx1 or ry2 <= ry1:
            return None

        region = np.array(source.crop((rx1, ry1, rx2, ry2)))
        if region.size == 0:
            return None

        lower = np.array([max(0, c - tolerance) for c in color])
        upper = np.array([min(255, c + tolerance) for c in color])
        mask = cv2.inRange(region[:, :, :3], lower, upper)

        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 1:
            return None

        # 取面积最大的连通域（排除零星噪点）
        areas = stats[1:, cv2.CC_STAT_AREA]
        best = 1 + int(np.argmax(areas))
        if int(stats[best, cv2.CC_STAT_AREA]) < min_pixels:
            return None

        bx = int(stats[best, cv2.CC_STAT_LEFT])
        by = int(stats[best, cv2.CC_STAT_TOP])
        bw = int(stats[best, cv2.CC_STAT_WIDTH])
        bh = int(stats[best, cv2.CC_STAT_HEIGHT])

        return (rx1 + bx, ry1 + by, rx1 + bx + bw, ry1 + by + bh)

    @staticmethod
    def find_template_scaled(source: Image.Image, template: Image.Image,
                             threshold: float = 0.8,
                             method: str = "sqdiff",
                             scales: Optional[List[float]] = None
                             ) -> Tuple[bool, Optional[Tuple[int, int]], float, float]:
        """多尺度模板匹配。

        ``cv2.matchTemplate`` 是单尺度的：模板与目标的像素尺寸必须严格一致，
        一旦 DPI 变化或窗口缩放就失效。本方法对模板做等比缩放后逐一尝试，
        取置信度最高者。

        代价：每个尺度一次完整匹配，耗时与尺度数成正比。仅在确实存在
        缩放场景时启用（``ImageConditionNode`` 的 ``multi_scale`` 开关）。

        Args:
            source: 源图像
            template: 模板图像
            threshold: 匹配阈值
            method: "sqdiff"（默认）/ "ccoeff"
            scales: 缩放比列表，None 或空表示单尺度（等价于 find_template）

        Returns:
            (是否找到, 中心位置, 置信度, 最佳缩放比)
        """
        if not scales:
            found, pos, conf = ImageProcessor.find_template(
                source, template, threshold, method
            )
            return found, pos, conf, 1.0

        best_pos: Optional[Tuple[int, int]] = None
        best_conf = -1.0
        best_scale = 1.0
        found_any = False

        for scale in scales:
            if abs(scale - 1.0) < 1e-6:
                scaled = template
            else:
                width = max(1, int(round(template.width * scale)))
                height = max(1, int(round(template.height * scale)))
                if width > source.width or height > source.height:
                    continue
                scaled = template.resize((width, height), Image.LANCZOS)

            found, pos, conf = ImageProcessor.find_template(
                source, scaled, threshold, method
            )
            if conf > best_conf:
                best_conf = conf
                best_pos = pos
                best_scale = scale
                found_any = found

        if best_conf < 0:
            return False, None, 0.0, 1.0
        return found_any, best_pos, max(0.0, best_conf), best_scale

    @staticmethod
    def find_color(source: Image.Image, target_color: Tuple[int, int, int],
                   tolerance: int = 10, match_mode: str = "any",
                   min_pixels: int = 1, match_ratio: float = 0.9
                   ) -> Tuple[bool, Optional[Tuple[int, int]]]:
        """颜色检测

        Args:
            source: 源图像
            target_color: 目标颜色 (R, G, B)
            tolerance: 容差
            match_mode: 匹配模式，"any"=任一像素匹配即可，"all"=匹配像素占比需达到 match_ratio
            min_pixels: any 模式下最小匹配像素数
            match_ratio: all 模式下匹配像素占比阈值

        Returns:
            (是否找到, 中心位置) 元组。位置为匹配像素的中位数位置。
        """
        source_array = np.array(source)

        lower = np.array([max(0, c - tolerance) for c in target_color])
        upper = np.array([min(255, c + tolerance) for c in target_color])

        mask = cv2.inRange(source_array[:, :, :3], lower, upper)

        positions = np.where(mask > 0)
        match_count = len(positions[0])

        if match_mode == "all":
            total_pixels = mask.size
            ratio = match_count / total_pixels if total_pixels > 0 else 0
            if ratio < match_ratio:
                return False, None
        else:
            if match_count < min_pixels:
                return False, None

        if match_count > 0:
            # 使用中位数位置（与 ColorConditionNode 原逻辑一致）
            center_idx = match_count // 2
            center_x = int(positions[1][center_idx])
            center_y = int(positions[0][center_idx])
            return True, (center_x, center_y)

        return False, None

    @staticmethod
    def compute_phash(image: Image.Image, hash_size: int = 8) -> str:
        img = image.convert('L').resize((32, 32))
        img_array = np.array(img, dtype=np.float64)
        
        dct = cv2.dct(img_array)
        
        dct_low = dct[:hash_size, :hash_size]
        
        dct_low_flat = dct_low.flatten()
        dct_low_flat_no_dc = dct_low_flat[1:]
        median = np.median(dct_low_flat_no_dc)
        
        diff = dct_low > median
        
        return ''.join(['1' if b else '0' for b in diff.flatten()])

    @staticmethod
    def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
        """计算差异哈希

        Args:
            image: PIL.Image 图像
            hash_size: 哈希大小

        Returns:
            哈希字符串
        """
        img_array = np.array(image.convert('L').resize((hash_size + 1, hash_size)))
        
        diff = img_array[:, 1:] > img_array[:, :-1]
        
        return ''.join(['1' if b else '0' for b in diff.flatten()])

    @staticmethod
    def compute_ahash(image: Image.Image, hash_size: int = 8) -> str:
        """计算平均哈希

        Args:
            image: PIL.Image 图像
            hash_size: 哈希大小

        Returns:
            哈希字符串
        """
        img_array = np.array(image.convert('L').resize((hash_size, hash_size)))
        
        avg = img_array.mean()
        
        diff = img_array > avg
        
        return ''.join(['1' if b else '0' for b in diff.flatten()])

    @staticmethod
    def hamming_distance(hash1: str, hash2: str) -> int:
        """计算汉明距离

        Args:
            hash1: 哈希字符串1
            hash2: 哈希字符串2

        Returns:
            汉明距离
        """
        if len(hash1) != len(hash2):
            return -1
        
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    @staticmethod
    def _get_template_hash(template: Image.Image, hash_func, hash_type: str) -> str:
        """获取模板哈希（带缓存）

        使用模板自身的 phash 作为缓存键，避免同一模板重复计算哈希。
        """
        cache_key = f"{ImageProcessor.compute_phash(template)}_{hash_type}"
        if cache_key not in ImageProcessor._template_hash_cache:
            ImageProcessor._template_hash_cache[cache_key] = hash_func(template)
        return ImageProcessor._template_hash_cache[cache_key]

    @staticmethod
    def find_by_hash(source: Image.Image, templates: List[Image.Image],
                    threshold: float = 5, hash_type: str = "phash") -> Tuple[bool, Optional[Tuple[int, int]], Optional[int]]:
        """基于哈希的图像查找

        使用粗-细两阶段搜索：先以模板尺寸 1/4 为步长粗搜索，再在命中点周围逐像素精搜索。

        Args:
            source: 源图像
            templates: 模板图像列表
            threshold: 最大汉明距离阈值
            hash_type: 哈希类型 (phash/dhash/ahash)

        Returns:
            (是否找到, 中心位置, 最佳匹配索引) 元组。未找到时第三个元素为 None。
        """
        if not templates:
            return False, None, None

        if hash_type == "phash":
            hash_func = ImageProcessor.compute_phash
        elif hash_type == "dhash":
            hash_func = ImageProcessor.compute_dhash
        else:
            hash_func = ImageProcessor.compute_ahash

        source_array = np.array(source)
        h, w = source_array.shape[:2]

        best_match = None
        best_distance = threshold + 1
        best_index = None

        for idx, template in enumerate(templates):
            template_hash = ImageProcessor._get_template_hash(template, hash_func, hash_type)

            template_array = np.array(template)
            th, tw = template_array.shape[:2]

            if th > h or tw > w:
                continue

            # 阶段1：粗搜索（步长 = 模板尺寸的 1/4）
            coarse_step_y = max(1, th // 4)
            coarse_step_x = max(1, tw // 4)
            coarse_candidates = []

            for y in range(0, h - th + 1, coarse_step_y):
                for x in range(0, w - tw + 1, coarse_step_x):
                    region = source.crop((x, y, x + tw, y + th))
                    source_hash = hash_func(region)
                    distance = ImageProcessor.hamming_distance(source_hash, template_hash)

                    if distance <= threshold:
                        coarse_candidates.append((distance, x, y))

            # 阶段2：在粗搜索命中点周围逐像素精搜索
            if coarse_candidates:
                coarse_candidates.sort()  # 按距离排序，优先搜索最佳候选
                for _, cx, cy in coarse_candidates[:3]:
                    y_start = max(0, cy - coarse_step_y)
                    y_end = min(h - th + 1, cy + coarse_step_y + 1)
                    x_start = max(0, cx - coarse_step_x)
                    x_end = min(w - tw + 1, cx + coarse_step_x + 1)

                    for y in range(y_start, y_end):
                        for x in range(x_start, x_end):
                            region = source.crop((x, y, x + tw, y + th))
                            source_hash = hash_func(region)
                            distance = ImageProcessor.hamming_distance(source_hash, template_hash)

                            if distance < best_distance:
                                best_distance = distance
                                best_match = (x + tw // 2, y + th // 2)
                                best_index = idx

                                if distance == 0:
                                    return True, best_match, best_index

        if best_match and best_distance <= threshold:
            return True, best_match, best_index

        return False, None, None
