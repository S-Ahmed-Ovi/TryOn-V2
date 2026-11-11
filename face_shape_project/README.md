# Face shape detection (MediaPipe, CPU only)

## Setup
    pip install -r requirements.txt
The first run downloads a small face model (~4 MB) into `models/`. If the download is blocked, the error message
shows the link and where to save the file.
(If `pip install mediapipe` fails, your Python is probably too new - create a virtual environment with Python 3.12.)

## Run
    python face_shape.py photo.jpg
    python face_shape.py my_photos_folder --stats
    python face_shape.py --db photos.db --table users --id-col id --blob-col photo      # photos stored as BLOBs (read-only)
Outputs: `output/face_shapes.json` and annotated pictures in `output/faces/` (look at them to check the result).
Nothing is written to any database.

## What you get per photo
    status                 ok | warn | reject
    issues                 plain-language messages to show the user ("Head is slightly turned", ...)
    face_shape             oval | round | square | heart | oblong   (None if rejected)
    confidence             0-0.85  (never higher: face shapes are fuzzy)
    alternatives           top 3 shapes with scores
    needs_confirmation     True -> show the user "Not quite right? Choose your face shape" (always allow override)
    measurements           length/cheek, jaw/cheek, forehead/jaw ratios, chin angle, yaw, roll ...

Photo checks: no face, more than one face, face cut off by the edge, face too small, head turned sideways (yaw),
head tilted (roll; measurements are corrected for tilt), chin up/down, blur.
NOT detected: hair covering forehead/jaw, hands or masks over the face, heavy beard, strong makeup/lighting.
Glasses are fine.

## IMPORTANT: tune before relying on it
The numbers in `PROTOTYPES` (top of face_shape.py) are first guesses, not calibrated on a real dataset.
1. Run `python face_shape.py your_photos --stats` and look at the spread and the shape counts.
   If nearly everything lands in one shape, the prototypes are off for your photos.
2. Look at 20-30 pictures in `output/faces/` and compare with what you see.
3. Adjust the centre values in `PROTOTYPES` (length/cheek, jaw/cheek, forehead/jaw, chin angle) and repeat.
Also check different skin tones, ages, hairstyles and lighting; landmark quality varies.

## Privacy
Face photos are personal data. Process them in memory, do not store them without clear consent, and say so on the page.
