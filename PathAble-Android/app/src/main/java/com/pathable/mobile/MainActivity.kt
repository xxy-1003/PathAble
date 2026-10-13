package com.pathable.mobile

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RectF
import android.os.Bundle
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.objectdetector.ObjectDetector
import java.nio.ByteBuffer
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private var detector: ObjectDetector? = null
    private var cameraProvider: ProcessCameraProvider? = null
    private var speech: TextToSpeech? = null
    private var speechReady = false
    private var running = false
    private var lastFrameTime = 0L
    private val lastWarning = mutableMapOf<String, Long>()
    private lateinit var preview: PreviewView
    private lateinit var overlay: DetectionOverlay
    private lateinit var status: TextView
    private lateinit var toggle: Button

    private val requestCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startDetection() else setStatus("Camera permission is needed.")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        preview = PreviewView(this).apply { scaleType = PreviewView.ScaleType.FIT_CENTER }
        overlay = DetectionOverlay()
        status = TextView(this).apply {
            text = "Tap Start to detect visible objects."
            textSize = 18f
            setTextColor(Color.WHITE)
            setPadding(24, 18, 24, 18)
            setBackgroundColor(Color.rgb(23, 43, 77))
        }
        toggle = Button(this).apply {
            text = "Start detection"
            setOnClickListener { if (running) stopDetection() else checkPermissionAndStart() }
        }
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(status)
            addView(toggle)
        }
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            addView(preview, FrameLayout.LayoutParams(-1, -1))
            addView(this@MainActivity.overlay, FrameLayout.LayoutParams(-1, -1))
            addView(panel, FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM))
        }
        setContentView(root)

        speech = TextToSpeech(this) { result ->
            speechReady = result == TextToSpeech.SUCCESS
            if (speechReady) speech?.language = Locale.ENGLISH
        }
    }

    private fun checkPermissionAndStart() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startDetection()
        } else {
            requestCamera.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startDetection() {
        if (running) return
        toggle.isEnabled = false
        setStatus("Loading object detector...")
        worker.execute {
            try {
                val options = ObjectDetector.ObjectDetectorOptions.builder()
                    .setBaseOptions(BaseOptions.builder().setModelAssetPath("efficientdet_lite0.tflite").build())
                    .setRunningMode(RunningMode.VIDEO)
                    .setScoreThreshold(0.40f)
                    .setMaxResults(10)
                    .build()
                detector = ObjectDetector.createFromOptions(this, options)
                runOnUiThread { bindCamera() }
            } catch (error: Exception) {
                runOnUiThread {
                    setStatus("Could not load detector: ${error.message}")
                    toggle.isEnabled = true
                }
            }
        }
    }

    private fun bindCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            try {
                val provider = future.get()
                cameraProvider = provider
                val cameraPreview = Preview.Builder().build().also {
                    it.surfaceProvider = preview.surfaceProvider
                }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()
                analysis.setAnalyzer(worker, ::analyze)
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, cameraPreview, analysis)
                running = true
                toggle.text = "Stop detection"
                toggle.isEnabled = true
                setStatus("Scanning. Possible obstacles will be announced.")
            } catch (error: Exception) {
                setStatus("Could not start camera: ${error.message}")
                toggle.isEnabled = true
                worker.execute { detector?.close(); detector = null }
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyze(image: ImageProxy) {
        try {
            val activeDetector = detector ?: return
            // Limit work on slower phones. CameraX drops queued frames automatically.
            val now = SystemClock.uptimeMillis()
            if (now - lastFrameTime < 100) return
            lastFrameTime = now

            val upright = image.toUprightBitmap()
            val input = BitmapImageBuilder(upright).build()
            val result = activeDetector.detectForVideo(input, now)
            val boxes = result.detections().mapNotNull { detection ->
                val category = detection.categories().firstOrNull() ?: return@mapNotNull null
                val bounds = detection.boundingBox()
                val name = category.categoryName().ifBlank { "object" }
                val danger = possibleObstacle(bounds, upright.width, upright.height)
                Mark(bounds, name, category.score(), danger)
            }
            val warning = boxes.firstOrNull { it.danger }
            runOnUiThread {
                if (!running) return@runOnUiThread
                overlay.show(boxes, upright.width, upright.height)
                if (warning == null) {
                    setStatus("${boxes.size} object(s) detected. No warning rule matched.")
                } else {
                    val direction = direction(warning.box.centerX(), upright.width)
                    val message = "Possible obstacle $direction: ${warning.name}"
                    setStatus(message)
                    val key = "${warning.name}:$direction"
                    val current = SystemClock.uptimeMillis()
                    if (current - (lastWarning[key] ?: 0L) >= 3000L) {
                        lastWarning[key] = current
                        if (speechReady) speech?.speak(message, TextToSpeech.QUEUE_FLUSH, null, "pathable-warning")
                    }
                }
            }
        } catch (error: Exception) {
            runOnUiThread { setStatus("Detection error: ${error.message}") }
        } finally {
            image.close()
        }
    }

    private fun possibleObstacle(box: RectF, width: Int, height: Int): Boolean {
        val x = box.centerX() / width
        val y = box.centerY() / height
        val area = box.width() * box.height() / (width.toFloat() * height)
        return x in 0.30f..0.70f && y >= 0.48f && area >= 0.035f
    }

    private fun direction(centerX: Float, width: Int): String = when {
        centerX / width < 0.38f -> "left"
        centerX / width > 0.62f -> "right"
        else -> "center"
    }

    private fun stopDetection() {
        running = false
        cameraProvider?.unbindAll()
        overlay.show(emptyList(), 1, 1)
        speech?.stop()
        worker.execute { detector?.close(); detector = null }
        lastWarning.clear()
        toggle.text = "Start detection"
        setStatus("Detection stopped.")
    }

    private fun setStatus(message: String) { status.text = message }

    override fun onDestroy() {
        running = false
        cameraProvider?.unbindAll()
        speech?.shutdown()
        worker.execute { detector?.close(); detector = null }
        worker.shutdown()
        super.onDestroy()
    }

    private fun ImageProxy.toUprightBitmap(): Bitmap {
        val plane = planes[0]
        val rowBytes = width * 4
        val pixels = ByteArray(rowBytes * height)
        val source = plane.buffer
        for (row in 0 until height) {
            source.position(row * plane.rowStride)
            source.get(pixels, row * rowBytes, rowBytes)
        }
        val original = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        original.copyPixelsFromBuffer(ByteBuffer.wrap(pixels))
        val rotation = imageInfo.rotationDegrees
        if (rotation == 0) return original
        val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
        return Bitmap.createBitmap(original, 0, 0, width, height, matrix, true).also { original.recycle() }
    }

    private data class Mark(val box: RectF, val name: String, val score: Float, val danger: Boolean)

    private inner class DetectionOverlay : View(this@MainActivity) {
        private var marks = emptyList<Mark>()
        private var frameWidth = 1
        private var frameHeight = 1
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 5f }
        private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 35f }

        fun show(newMarks: List<Mark>, width: Int, height: Int) {
            marks = newMarks
            frameWidth = width
            frameHeight = height
            invalidate()
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val scale = minOf(width.toFloat() / frameWidth, height.toFloat() / frameHeight)
            val dx = (width - frameWidth * scale) / 2
            val dy = (height - frameHeight * scale) / 2
            for (mark in marks) {
                paint.color = if (mark.danger) Color.RED else Color.GREEN
                val b = mark.box
                val rect = RectF(dx + b.left * scale, dy + b.top * scale, dx + b.right * scale, dy + b.bottom * scale)
                canvas.drawRect(rect, paint)
                canvas.drawText("${mark.name} ${(mark.score * 100).toInt()}%", rect.left, maxOf(36f, rect.top - 8f), labelPaint)
            }
        }
    }
}
