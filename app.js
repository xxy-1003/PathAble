
const video = document.getElementById("camera");
const statusText = document.getElementById("status");
const startButton = document.getElementById("startCamera");

// OpenCV and camera state
let cvReady = false;
let processing = false;
let stream = null;
let cap = null;
let src = null;
let gray = null;
let edges = null;
let rafId = null;

// Wait for OpenCV to become available.
function checkOpenCV() {
    if (
        typeof cv !== "undefined" &&
        typeof cv.Mat === "function" &&
        typeof cv.VideoCapture === "function" &&
        typeof cv.Canny === "function"
    ) {
        cvReady = true;
        statusText.textContent =
            "OpenCV ready. Start the camera to test image processing.";
    }
}

const cvCheckTimer = setInterval(() => {
    checkOpenCV();

    if (cvReady) {
        clearInterval(cvCheckTimer);
    }
}, 500);

checkOpenCV();

// Create the processing canvas.
const canvas = document.createElement("canvas");
canvas.id = "processedCanvas";
canvas.style.width = "100%";
canvas.style.borderRadius = "12px";
canvas.style.marginTop = "12px";
canvas.style.background = "#172b4d";
video.insertAdjacentElement("afterend", canvas);

const context = canvas.getContext("2d");

function releaseMats() {
    if (src) src.delete();
    if (gray) gray.delete();
    if (edges) edges.delete();

    src = null;
    gray = null;
    edges = null;
    cap = null;
}

function processFrame() {
    if (!processing || !cvReady || video.readyState < 2) {
        return;
    }

    try {
        cap.read(src);

        // Convert the camera frame to grayscale.
        cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);

        // Detect edges in the grayscale image.
        cv.Canny(gray, edges, 80, 160);

        // Display the processed image.
        cv.imshow(canvas, edges);
    } catch (error) {
        processing = false;
        releaseMats();
        statusText.textContent =
            "Image processing error: " + error.message;
        console.error(error);
        return;
    }

    rafId = requestAnimationFrame(processFrame);
}

startButton.addEventListener("click", async () => {
    if (!cvReady) {
        checkOpenCV();

        if (!cvReady) {
            statusText.textContent =
                "OpenCV is not ready. Please refresh and try again.";
            return;
        }
    }

    try {
        // Stop an existing camera session before restarting.
        processing = false;

        if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }

        releaseMats();

        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }

        statusText.textContent = "Starting camera...";

        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 640 },
                height: { ideal: 480 }
            },
            audio: false
        });

        video.srcObject = stream;
        await video.play();

        // Wait for actual video dimensions.
        if (!video.videoWidth || !video.videoHeight) {
            await new Promise(resolve => {
                video.addEventListener("loadedmetadata", resolve, {
                    once: true
                });
            });
        }

        // Allocate reusable OpenCV matrices.
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        cap = new cv.VideoCapture(video);
        src = new cv.Mat(
            video.videoHeight,
            video.videoWidth,
            cv.CV_8UC4
        );
        gray = new cv.Mat(
            video.videoHeight,
            video.videoWidth,
            cv.CV_8UC1
        );
        edges = new cv.Mat(
            video.videoHeight,
            video.videoWidth,
            cv.CV_8UC1
        );

        processing = true;
        statusText.textContent =
            "PathAble is processing live camera frames.";
        processFrame();

    } catch (error) {
        processing = false;
        releaseMats();

        statusText.textContent =
            "Camera or OpenCV error: " + error.message;
        console.error(error);
    }
});

// Clean up resources if the page is closed or refreshed.
window.addEventListener("beforeunload", () => {
    processing = false;

    if (rafId !== null) {
        cancelAnimationFrame(rafId);
    }

    releaseMats();

    if (stream) {
        stream.getTracks().forEach(track => track.stop());
    }
});
