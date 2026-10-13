
const video = document.getElementById("camera");
const statusText = document.getElementById("status");
const startButton = document.getElementById("startCamera");

let cvReady = false;

if (typeof cv !== "undefined") {
    cv.onRuntimeInitialized = () => {
        cvReady = true;
        statusText.textContent = "OpenCV loaded. Ready to test.";
    };

    // Handle builds that expose OpenCV as a Promise.
    if (cv instanceof Promise) {
        cv.then((loadedCv) => {
            window.cv = loadedCv;
            cvReady = true;
            statusText.textContent = "OpenCV loaded. Ready to test.";
        }).catch(() => {
            statusText.textContent = "OpenCV failed to initialise.";
        });
    }
} else {
    statusText.textContent = "Waiting for OpenCV...";
}

startButton.addEventListener("click", async () => {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: { ideal: "environment" }
            },
            audio: false
        });

        video.srcObject = stream;
        await video.play();

        statusText.textContent = cvReady
            ? "Camera and OpenCV ready."
            : "Camera ready. Waiting for OpenCV.";
    } catch (error) {
        statusText.textContent =
            "Camera error: " + error.message;
    }
});
